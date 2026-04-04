"""
db.py — Database write operations for the aggregator.

Uses SQLAlchemy async sessions. The session factory is initialised in
main.py after migrations have run.
"""

from __future__ import annotations

from datetime import datetime, timezone

import time

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from csi_models import CsiSample, Receiver, ReceiverHeartbeat, get_session_factory

from .metrics import batch_size, batch_write_duration, batch_writes
from .parser import CSIPacket

log = structlog.get_logger(__name__)


async def get_or_create_receiver_id(name: str, mac: str) -> int:
    """
    Return the DB id for a receiver by name.
    If not found, auto-register it — admin can fill in floor/location later.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(Receiver.id).where(Receiver.name == name)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            return row

        stmt = (
            pg_insert(Receiver)
            .values(mac=mac, name=name, role="receiver", active=True)
            .on_conflict_do_update(
                index_elements=["mac"],
                set_={"name": name},
            )
            .returning(Receiver.id)
        )
        result = await session.execute(stmt)
        await session.commit()
        new_id: int = result.scalar_one()
        log.info("receiver.registered", name=name, mac=mac, id=new_id)
        return new_id


async def insert_batch(batch: list[tuple[datetime, int, CSIPacket]]) -> None:
    """Bulk-insert a list of (wall_time, receiver_id, packet) tuples."""
    if not batch:
        return

    rows = [
        {
            "time": wall_time,
            "receiver_id": receiver_id,
            "transmitter_mac": pkt.transmitter_mac,
            "rssi": pkt.rssi,
            "noise_floor": pkt.noise_floor,
            "channel": pkt.channel,
            "bandwidth": pkt.bandwidth_mhz,
            "antenna_count": pkt.antenna_count,
            "subcarrier_count": pkt.subcarrier_count,
            "amplitude": pkt.amplitude,
            "phase": pkt.phase,
        }
        for wall_time, receiver_id, pkt in batch
    ]

    t0 = time.perf_counter()
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            await session.execute(pg_insert(CsiSample), rows)
            await session.commit()
        elapsed = time.perf_counter() - t0
        batch_writes.labels(status="success").inc()
        batch_write_duration.observe(elapsed)
        batch_size.observe(len(rows))
        log.debug("db.batch_inserted", count=len(rows), duration_ms=round(elapsed * 1000, 1))
    except Exception:
        batch_writes.labels(status="error").inc()
        raise


async def upsert_heartbeat(
    receiver_id: int,
    ip_address: str | None = None,
) -> None:
    """Update last_seen for a receiver. Called periodically by the batch writer."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = (
            pg_insert(ReceiverHeartbeat)
            .values(
                receiver_id=receiver_id,
                last_seen=datetime.now(tz=timezone.utc),
                ip_address=ip_address,
            )
            .on_conflict_do_update(
                index_elements=["receiver_id"],
                set_={
                    "last_seen": datetime.now(tz=timezone.utc),
                    "ip_address": ip_address,
                },
            )
        )
        await session.execute(stmt)
        await session.commit()
