"""
main.py — Nornir training daemon.

Startup sequence:
  1. Configure structlog (JSON).
  2. Start Prometheus HTTP server on ``METRICS_PORT``.
  3. Register with Freki via ``/api/training-daemons/heartbeat``.
  4. Enter the claim-loop: poll queued jobs, race to claim, train, upload,
     report complete/fail. Heartbeat the daemon row every
     ``DAEMON_HEARTBEAT_S`` seconds and the job row every
     ``JOB_HEARTBEAT_S`` seconds while a job is running.

Environment variables:
  FREKI_URL                base URL for Freki (default http://freki:8000)
  DAEMON_NAME              unique daemon name (default socket.gethostname())
  DAEMON_HOST              human-readable host label (default DAEMON_NAME)
  POLL_INTERVAL_S          how often to scan for queued jobs (default 10)
  DAEMON_HEARTBEAT_S       daemon-row heartbeat cadence (default 30)
  JOB_HEARTBEAT_S          job-row heartbeat cadence (default 15)
  METRICS_PORT             Prometheus port, 0 to disable (default 8001)
  LOG_LEVEL                debug | info | warning | error (default info)
  MODEL_UPLOAD_SHARED_SECRET shared secret sent on POST /api/models when set

The training target is the ``label`` column on ``training_samples`` (room
name). Per issue #14, ``labels.occupants`` is out of scope for v1; Völva
maps the predicted room to ``{room: {human_count: 1}}`` downstream.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket

import structlog
from prometheus_client import start_http_server

from .freki_client import FrekiClient, FrekiError
from .metrics import jobs_claimed, jobs_completed, jobs_failed, queue_depth
from .train import run_job

# ── Config ────────────────────────────────────────────────────────────────────

FREKI_URL = os.environ.get("FREKI_URL", "http://freki:8000")
DAEMON_NAME = os.environ.get("DAEMON_NAME", socket.gethostname())
DAEMON_HOST = os.environ.get("DAEMON_HOST", DAEMON_NAME)
POLL_INTERVAL_S = float(os.environ.get("POLL_INTERVAL_S", "10"))
DAEMON_HEARTBEAT_S = float(os.environ.get("DAEMON_HEARTBEAT_S", "30"))
JOB_HEARTBEAT_S = float(os.environ.get("JOB_HEARTBEAT_S", "15"))
METRICS_PORT = int(os.environ.get("METRICS_PORT", "8001"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").upper()
MODEL_UPLOAD_SHARED_SECRET = os.environ.get("MODEL_UPLOAD_SHARED_SECRET", "")

CAPABILITIES = {
    "model_types": ["random_forest"],
    "max_rooms": 32,
}

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, LOG_LEVEL, logging.INFO)),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)
log = structlog.get_logger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _local_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 53))
            return s.getsockname()[0]
    except OSError:
        return None


async def _periodic_job_heartbeat(client: FrekiClient, job_id: int, stop: asyncio.Event) -> None:
    """Ping Freki every JOB_HEARTBEAT_S while a job is training."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=JOB_HEARTBEAT_S)
            return
        except TimeoutError:
            try:
                await client.heartbeat_job(job_id)
            except FrekiError as exc:
                log.warning("job.heartbeat_failed", job_id=job_id, error=str(exc))


async def _register_daemon(client: FrekiClient) -> int:
    daemon = await client.heartbeat_daemon(
        name=DAEMON_NAME,
        host=DAEMON_HOST,
        ip_address=_local_ip(),
        capabilities=CAPABILITIES,
    )
    log.info("daemon.registered", daemon_id=daemon["id"], name=DAEMON_NAME)
    return daemon["id"]


async def _execute_job(client: FrekiClient, job: dict) -> None:
    """Run one claimed job to completion: train, upload, report."""
    job_id = job["id"]
    stop_hb = asyncio.Event()
    hb_task = asyncio.create_task(_periodic_job_heartbeat(client, job_id, stop_hb))

    try:
        try:
            model_bytes, metrics, feature_config = await run_job(client=client, job=job)
        except Exception as exc:
            log.error("job.training_failed", job_id=job_id, error=str(exc))
            jobs_failed.labels(stage="train").inc()
            try:
                await client.fail_job(job_id, f"training error: {exc}")
            except FrekiError as report_exc:
                jobs_failed.labels(stage="report").inc()
                log.error("job.fail_report_failed", job_id=job_id, error=str(report_exc))
            return

        try:
            uploaded = await client.upload_model(
                name=f"job-{job_id}-{DAEMON_NAME}",
                model_bytes=model_bytes,
                metrics=metrics,
                feature_config=feature_config,
                training_job_id=job_id,
            )
        except FrekiError as exc:
            log.error("job.upload_failed", job_id=job_id, error=str(exc))
            jobs_failed.labels(stage="upload").inc()
            try:
                await client.fail_job(job_id, f"model upload error: {exc}")
            except FrekiError as report_exc:
                jobs_failed.labels(stage="report").inc()
                log.error("job.fail_report_failed", job_id=job_id, error=str(report_exc))
            return

        try:
            await client.complete_job(job_id)
        except FrekiError as exc:
            # Model landed but we couldn't mark complete — log loudly and
            # let the orphan reaper re-queue. Not incrementing completed
            # keeps the counter honest.
            jobs_failed.labels(stage="report").inc()
            log.error("job.complete_report_failed", job_id=job_id, error=str(exc))
            return

        jobs_completed.inc()
        log.info(
            "job.done",
            job_id=job_id,
            model_id=uploaded["id"],
            accuracy=metrics.get("accuracy"),
        )
    finally:
        stop_hb.set()
        await hb_task


async def _claim_and_run(client: FrekiClient, daemon_id: int) -> bool:
    """Try to claim and run one queued job. Returns True if something ran."""
    try:
        queued = await client.list_queued_jobs()
    except FrekiError as exc:
        log.warning("jobs.list_failed", error=str(exc))
        return False

    queue_depth.set(len(queued))
    if not queued:
        return False

    # Freki returns newest first; reverse so we favour the oldest queued job.
    for job in reversed(queued):
        try:
            claimed = await client.claim_job(job["id"], daemon_id)
        except FrekiError as exc:
            log.warning("job.claim_failed", job_id=job["id"], error=str(exc))
            continue
        if claimed is None:
            continue
        jobs_claimed.inc()
        log.info("job.claimed", job_id=claimed["id"], rooms=claimed["spec"]["rooms"])
        await _execute_job(client, claimed)
        return True

    return False


async def _daemon_heartbeat_loop(client: FrekiClient, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=DAEMON_HEARTBEAT_S)
            return
        except TimeoutError:
            try:
                await client.heartbeat_daemon(
                    name=DAEMON_NAME,
                    host=DAEMON_HOST,
                    ip_address=_local_ip(),
                    capabilities=CAPABILITIES,
                )
            except FrekiError as exc:
                log.warning("daemon.heartbeat_failed", error=str(exc))


async def main() -> None:
    log.info(
        "nornir.starting",
        freki=FREKI_URL,
        daemon_name=DAEMON_NAME,
        model_upload_secret=bool(MODEL_UPLOAD_SHARED_SECRET),
    )

    if METRICS_PORT > 0:
        start_http_server(METRICS_PORT)
        log.info("metrics.listening", port=METRICS_PORT)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    async with FrekiClient(
        FREKI_URL,
        model_upload_shared_secret=MODEL_UPLOAD_SHARED_SECRET,
    ) as client:
        # Retry initial registration until Freki is reachable.
        while not stop_event.is_set():
            try:
                daemon_id = await _register_daemon(client)
                break
            except (FrekiError, OSError) as exc:
                log.warning("daemon.registration_failed", error=str(exc))
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_S)
                    return
                except TimeoutError:
                    continue
        else:
            return

        hb_task = asyncio.create_task(_daemon_heartbeat_loop(client, stop_event))
        try:
            while not stop_event.is_set():
                ran = await _claim_and_run(client, daemon_id)
                if not ran:
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_S)
                    except TimeoutError:
                        pass
        finally:
            stop_event.set()
            await hb_task

    log.info("nornir.stopped")


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
