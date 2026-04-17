"""
main.py — Nornir training daemon

Startup sequence:
  1. Detect hardware capabilities
  2. Register with Freki via heartbeat
  3. Enter main loop: heartbeat → poll for queued job → train → upload

Environment variables:
  FREKI_URL                 http://freki:8000
  DAEMON_NAME               unique name for this instance
  HEARTBEAT_INTERVAL_S      idle heartbeat period (default 30)
  JOB_HEARTBEAT_INTERVAL_S  heartbeat period during active training (default 10)
  LOG_LEVEL                 debug | info | warning | error (default info)
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import traceback

import structlog

from .client import FrekiClient
from .hardware import detect as detect_hardware
from .train import train_model

FREKI_URL = os.environ["FREKI_URL"]
DAEMON_NAME = os.environ["DAEMON_NAME"]
HEARTBEAT_INTERVAL_S = int(os.environ.get("HEARTBEAT_INTERVAL_S", "30"))
JOB_HEARTBEAT_INTERVAL_S = int(os.environ.get("JOB_HEARTBEAT_INTERVAL_S", "10"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info")

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)
log = structlog.get_logger(__name__)


async def _job_heartbeat_loop(client: FrekiClient, job_id: int, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await client.job_heartbeat(job_id)
        except Exception:
            log.warning("job_heartbeat.failed", job_id=job_id)
        await asyncio.sleep(JOB_HEARTBEAT_INTERVAL_S)


async def _run_job(client: FrekiClient, job: dict) -> None:
    job_id: int = job["id"]
    spec: dict = job["spec"]
    log.info("training_job.starting", job_id=job_id, model_type=spec.get("model_type"))

    stop_event = asyncio.Event()
    heartbeat_task = asyncio.create_task(_job_heartbeat_loop(client, job_id, stop_event))

    try:
        model_bytes, metrics, feature_config = await train_model(client, job_id, spec)
        stop_event.set()
        heartbeat_task.cancel()

        log.info(
            "training_job.trained",
            job_id=job_id,
            accuracy=metrics.get("accuracy"),
            n_samples=metrics.get("n_samples"),
        )

        model_name = f"{spec.get('model_type', 'model')}_job{job_id}"
        await client.upload_model_with_retry(
            name=model_name,
            model_bytes=model_bytes,
            metrics=metrics,
            feature_config=feature_config,
            training_job_id=job_id,
        )
        await client.complete_job(job_id)
        log.info("training_job.complete", job_id=job_id)

    except Exception as exc:
        stop_event.set()
        heartbeat_task.cancel()
        error_msg = traceback.format_exc()
        log.error("training_job.failed", job_id=job_id, error=str(exc))
        try:
            await client.fail_job(job_id, error_msg[:2000])
        except Exception:
            log.warning("training_job.fail_report_error", job_id=job_id)


async def _main() -> None:
    host = socket.gethostname()
    capabilities = detect_hardware()
    log.info("nornir.starting", daemon=DAEMON_NAME, host=host, capabilities=capabilities)

    client = FrekiClient(base_url=FREKI_URL, daemon_name=DAEMON_NAME)
    try:
        while True:
            try:
                await client.heartbeat(host=host, capabilities=capabilities)
                job = await client.poll_queued_job()
                if job:
                    claimed = await client.claim_job(job["id"])
                    if claimed["status"] == "running":
                        await _run_job(client, claimed)
            except Exception:
                log.warning("nornir.loop_error")
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
    finally:
        await client.aclose()


def run() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    run()
