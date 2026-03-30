"""
main.py — Geri (CSI Aggregator)

Startup sequence:
  1. Connect asyncpg pool to TimescaleDB
  2. Bind UDP socket
  3. Batch-write CSI packets to TimescaleDB

Environment variables:
  DATABASE_URL      postgresql://user:pass@host:5432/csi  (required)
  UDP_HOST          bind address (default 0.0.0.0)
  UDP_PORT          bind port (default 5005)
  BATCH_SIZE        rows to buffer before flushing (default 50)
  BATCH_TIMEOUT_MS  max ms before flushing a partial batch (default 500)
  LOG_LEVEL         debug | info | warning | error (default info)
"""

from __future__ import annotations

import asyncio
import os
import signal
from datetime import datetime, timezone

import structlog

from .db import create_pool, get_receiver_id, insert_batch
from .parser import ParseError, parse_packet

# ── Config ────────────────────────────────────────────────────────────────────

DATABASE_URL     = os.environ["DATABASE_URL"]
UDP_HOST         = os.environ.get("UDP_HOST", "0.0.0.0")
UDP_PORT         = int(os.environ.get("UDP_PORT", "5005"))
BATCH_SIZE       = int(os.environ.get("BATCH_SIZE", "50"))
BATCH_TIMEOUT_MS = int(os.environ.get("BATCH_TIMEOUT_MS", "500"))
LOG_LEVEL        = os.environ.get("LOG_LEVEL", "info").upper()

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(__import__("logging"), LOG_LEVEL, 20)
    )
)
log = structlog.get_logger(__name__)

# ── UDP Protocol ──────────────────────────────────────────────────────────────


class CSIUDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue) -> None:
        self._queue = queue
        self._transport: asyncio.DatagramTransport | None = None
        self._dropped = 0

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self._transport = transport
        log.info("udp.listening", host=UDP_HOST, port=UDP_PORT)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            pkt = parse_packet(data)
        except ParseError as exc:
            log.warning("udp.parse_error", addr=addr, error=str(exc))
            return

        wall_time = datetime.now(tz=timezone.utc)
        try:
            self._queue.put_nowait((wall_time, pkt))
        except asyncio.QueueFull:
            self._dropped += 1
            if self._dropped % 100 == 1:
                log.warning("udp.queue_full", dropped_total=self._dropped)

    def error_received(self, exc: Exception) -> None:
        log.error("udp.error", error=str(exc))

    def connection_lost(self, exc: Exception | None) -> None:
        log.warning("udp.connection_lost", error=str(exc) if exc else None)


# ── Batch writer ──────────────────────────────────────────────────────────────


async def batch_writer(queue: asyncio.Queue, pool) -> None:
    """Drain the queue and write to DB in batches."""
    timeout = BATCH_TIMEOUT_MS / 1000.0
    batch: list = []

    while True:
        deadline = asyncio.get_event_loop().time() + timeout

        while len(batch) < BATCH_SIZE:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                wall_time, pkt = await asyncio.wait_for(queue.get(), timeout=remaining)
                receiver_id = await get_receiver_id(pool, pkt)
                batch.append((wall_time, receiver_id, pkt))
            except asyncio.TimeoutError:
                break

        if batch:
            try:
                await insert_batch(pool, batch)
            except Exception as exc:
                log.error("db.insert_error", error=str(exc), batch_size=len(batch))
                # Don't drop — sleep briefly and retry once
                await asyncio.sleep(1)
                try:
                    await insert_batch(pool, batch)
                except Exception as exc2:
                    log.error("db.insert_retry_failed", error=str(exc2))
            finally:
                batch = []


# ── Main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    log.info("geri.starting", udp_port=UDP_PORT, batch_size=BATCH_SIZE)

    pool = await create_pool(DATABASE_URL)

    queue: asyncio.Queue = asyncio.Queue(maxsize=BATCH_SIZE * 20)

    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: CSIUDPProtocol(queue),
        local_addr=(UDP_HOST, UDP_PORT),
    )

    writer_task = asyncio.create_task(batch_writer(queue, pool))

    stop_event = asyncio.Event()

    def _shutdown(signum, frame):
        log.info("geri.shutdown_requested", signal=signum)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _shutdown)

    log.info("geri.ready")
    await stop_event.wait()

    log.info("geri.draining")
    transport.close()
    writer_task.cancel()
    await pool.close()
    log.info("geri.stopped")


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
