"""
main.py — CSI Aggregator

Startup sequence:
  1. Run Alembic migrations (idempotent)
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
from datetime import datetime, timezone

import structlog

from csi_models import init_engine, run_migrations

from .db import get_or_create_receiver_id, insert_batch, upsert_heartbeat
from .parser import ParseError, parse_packet

# ── Config ────────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ["DATABASE_URL"]
UDP_HOST = os.environ.get("UDP_HOST", "0.0.0.0")
UDP_PORT = int(os.environ.get("UDP_PORT", "5005"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "50"))
BATCH_TIMEOUT_MS = int(os.environ.get("BATCH_TIMEOUT_MS", "500"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").upper()

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, LOG_LEVEL, logging.INFO)
    )
)
log = structlog.get_logger(__name__)

# ── UDP Protocol ──────────────────────────────────────────────────────────────


class CSIUDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue) -> None:
        self._queue = queue
        self._dropped = 0

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        log.info("udp.listening", host=UDP_HOST, port=UDP_PORT)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            pkt = parse_packet(data)
        except ParseError as exc:
            log.warning("udp.parse_error", addr=addr, error=str(exc))
            return

        wall_time = datetime.now(tz=timezone.utc)
        try:
            self._queue.put_nowait((wall_time, addr[0], pkt))
        except asyncio.QueueFull:
            self._dropped += 1
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
            wall_time, src_ip, pkt = await asyncio.wait_for(
                queue.get(), timeout=timeout
            )
        except asyncio.TimeoutError:
            if batch:
                await insert_batch(batch)
                batch = []
            continue
        except asyncio.CancelledError:
            if batch:
                await insert_batch(batch)
            return

        if pkt.receiver_name not in receiver_cache:
            receiver_id = await get_or_create_receiver_id(
                pkt.receiver_name, pkt.transmitter_mac
            )
            receiver_cache[pkt.receiver_name] = receiver_id
        receiver_id = receiver_cache[pkt.receiver_name]

        now = asyncio.get_event_loop().time()
        if now - last_heartbeat.get(receiver_id, 0.0) > heartbeat_interval:
            await upsert_heartbeat(receiver_id, ip_address=src_ip)
            last_heartbeat[receiver_id] = now

        batch.append((wall_time, receiver_id, pkt))
        if len(batch) >= BATCH_SIZE:
            await insert_batch(batch)
            batch = []


# ── Main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    log.info("aggregator.starting")

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
