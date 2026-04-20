"""
main.py — CSI Aggregator

Startup sequence:
  1. Run bundled SQL bootstrap migrations (idempotent)
  2. Initialise SQLAlchemy async engine
  3. Bind UDP socket
  4. Batch-write CSI packets to TimescaleDB

Environment variables:
  DATABASE_URL      postgresql+asyncpg://user:pass@host:5432/csi
  UDP_HOST          bind address (default 0.0.0.0)
  UDP_PORT          bind port (default 5005)
  BATCH_SIZE        rows to buffer before flushing (default 50)
  BATCH_TIMEOUT_MS  max ms before flushing a partial batch (default 500)
  LOG_LEVEL         debug | info | warning | error (default info)
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from datetime import UTC, datetime

import structlog
from csi_models import init_engine, run_migrations
from prometheus_client import start_http_server

from .db import get_or_create_receiver_id, insert_batch, upsert_heartbeat
from .metrics import packets_dropped, packets_invalid, packets_received, receiver_last_seen
from .parser import ParseError, parse_packet

# ── Config ────────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ["DATABASE_URL"]
UDP_HOST = os.environ.get("UDP_HOST", "0.0.0.0")
UDP_PORT = int(os.environ.get("UDP_PORT", "5005"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "50"))
BATCH_TIMEOUT_MS = int(os.environ.get("BATCH_TIMEOUT_MS", "500"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").upper()
# Set to 0 to disable the Prometheus HTTP server
METRICS_PORT = int(os.environ.get("METRICS_PORT", "8001"))
ACK_INTERVAL_S = float(os.environ.get("ACK_INTERVAL_S", "5"))
ACK_PAYLOAD = b"grimnir-ack"

_log_level_int = getattr(logging, LOG_LEVEL, logging.INFO)
_shared_processors = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.StackInfoRenderer(),
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.ExceptionRenderer(),
]
structlog.configure(
    processors=[
        *_shared_processors,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.make_filtering_bound_logger(_log_level_int),
    context_class=dict,
    cache_logger_on_first_use=True,
)
_handler = logging.StreamHandler()
_handler.setFormatter(
    structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=_shared_processors,
    )
)
logging.root.handlers = [_handler]
logging.root.setLevel(_log_level_int)
log = structlog.get_logger(__name__)

# ── UDP Protocol ──────────────────────────────────────────────────────────────


class CSIUDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue) -> None:
        self._queue = queue
        self._dropped = 0
        self._last_ack_sent: dict[tuple[str, int], float] = {}
        self._transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self._transport = transport
        log.info("udp.listening", host=UDP_HOST, port=UDP_PORT)

    def _maybe_send_ack(self, addr: tuple[str, int]) -> None:
        if self._transport is None:
            return

        now = asyncio.get_running_loop().time()
        if now - self._last_ack_sent.get(addr, 0.0) < ACK_INTERVAL_S:
            return

        self._transport.sendto(ACK_PAYLOAD, addr)
        self._last_ack_sent[addr] = now

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            pkt = parse_packet(data)
        except ParseError as exc:
            log.warning("udp.parse_error", addr=addr, error=str(exc))
            packets_invalid.inc()
            return

        self._maybe_send_ack(addr)
        packets_received.labels(receiver_name=pkt.receiver_name).inc()
        wall_time = datetime.now(tz=UTC)
        try:
            self._queue.put_nowait((wall_time, addr[0], pkt))
        except asyncio.QueueFull:
            self._dropped += 1
            packets_dropped.inc()
            if self._dropped % 100 == 1:
                log.warning("udp.queue_full", dropped_total=self._dropped)

    def error_received(self, exc: Exception) -> None:
        log.error("udp.error", error=str(exc))


# ── Batch writer ──────────────────────────────────────────────────────────────


async def batch_writer(queue: asyncio.Queue) -> None:
    """Drain the queue and write to the DB in batches."""
    receiver_cache: dict[str, int] = {}
    last_heartbeat: dict[int, float] = {}
    heartbeat_interval = 10.0

    batch: list = []
    timeout = BATCH_TIMEOUT_MS / 1000.0

    while True:
        try:
            wall_time, src_ip, pkt = await asyncio.wait_for(queue.get(), timeout=timeout)
        except TimeoutError:
            if batch:
                try:
                    await insert_batch(batch)
                except Exception as exc:
                    log.error("batch.insert_failed", count=len(batch), error=str(exc))
                batch = []
            continue
        except asyncio.CancelledError:
            if batch:
                await insert_batch(batch)
            return

        try:
            if pkt.receiver_name not in receiver_cache:
                receiver_id = await get_or_create_receiver_id(
                    pkt.receiver_name, pkt.transmitter_mac
                )
                receiver_cache[pkt.receiver_name] = receiver_id
            receiver_id = receiver_cache[pkt.receiver_name]
        except Exception as exc:
            log.error("receiver.lookup_failed", receiver_name=pkt.receiver_name, error=str(exc))
            continue

        now = asyncio.get_running_loop().time()
        if now - last_heartbeat.get(receiver_id, 0.0) > heartbeat_interval:
            try:
                await upsert_heartbeat(receiver_id, ip_address=src_ip)
            except Exception as exc:
                log.warning("heartbeat.failed", receiver_id=receiver_id, error=str(exc))
            else:
                last_heartbeat[receiver_id] = now
                receiver_last_seen.labels(receiver_name=pkt.receiver_name).set(time.time())

        batch.append((wall_time, receiver_id, pkt))
        if len(batch) >= BATCH_SIZE:
            try:
                await insert_batch(batch)
            except Exception as exc:
                log.error("batch.insert_failed", count=len(batch), error=str(exc))
            batch = []


# ── Main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    log.info("aggregator.starting")

    if METRICS_PORT > 0:
        start_http_server(METRICS_PORT)
        log.info("metrics.listening", port=METRICS_PORT)

    log.info("migrations.running")
    run_migrations(DATABASE_URL)
    log.info("migrations.done")

    init_engine(DATABASE_URL)
    log.info("db.engine_initialised")

    queue: asyncio.Queue = asyncio.Queue(maxsize=10_000)
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: CSIUDPProtocol(queue),
        local_addr=(UDP_HOST, UDP_PORT),
    )

    writer_task = asyncio.create_task(batch_writer(queue))

    def _on_writer_done(task: asyncio.Task) -> None:
        if not task.cancelled() and (exc := task.exception()):
            log.error("batch_writer.crashed", error=str(exc))

    writer_task.add_done_callback(_on_writer_done)
    stop_event = asyncio.Event()

    def _shutdown(sig, _frame):
        log.info("aggregator.shutdown", signal=sig)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _shutdown)

    log.info("aggregator.ready")
    await stop_event.wait()

    log.info("aggregator.draining")
    transport.close()
    writer_task.cancel()
    await asyncio.gather(writer_task, return_exceptions=True)
    log.info("aggregator.stopped")


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
