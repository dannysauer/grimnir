"""
db.py — Database write operations for the aggregator.

Uses SQLAlchemy async sessions. The session factory is initialised in
main.py after migrations have run.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime

import structlog
from csi_models import CsiSample, Receiver, ReceiverHeartbeat, get_session_factory
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .metrics import batch_size, batch_write_duration, batch_writes
from .parser import CSIPacket

log = structlog.get_logger(__name__)


def _receiver_mac(name: str) -> str:
    """
    Derive a stable locally-administered MAC from a receiver name.

    Receiver boards don't include their own MAC in the CSI packet — only the
    transmitter MAC is present. To satisfy the unique mac constraint on the
    receivers table without collisions between receivers sharing a transmitter,
    we generate a deterministic locally-administered MAC from the receiver name.
    """
    digest = hashlib.sha256(name.encode()).digest()[:6]
    # Set locally-administered bit (bit 1), clear multicast bit (bit 0)
    first_byte = (digest[0] | 0x02) & 0xFE
    return ":".join(f"{b:02x}" for b in [first_byte, *digest[1:]])


async def get_or_create_receiver_id(name: str, transmitter_mac: str) -> int:
    """
    Return the DB id for a receiver by name.
    If not found, auto-register it — admin can fill in floor/location later.

    Note: transmitter_mac is passed for logging context only. The receivers.mac
    column stores a stable synthetic MAC derived from the receiver name, since
    the CSI packet format does not carry the receiver's own hardware MAC.
    """
    mac = _receiver_mac(name)
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(Receiver).where(Receiver.name == name))
        receiver = result.scalar_one_or_none()
        if receiver is not None:
            return receiver.id

        stmt = (
            pg_insert(Receiver)
            .values(mac=mac, name=name, role="receiver", active=True)
            .on_conflict_do_update(
                index_elements=["name"],
                set_={"active": True},
            )
            .returning(Receiver.id)
        )
        result = await session.execute(stmt)
        await session.commit()
        new_id: int = result.scalar_one()
        log.info("receiver.registered", name=name, transmitter_mac=transmitter_mac, id=new_id)
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
                last_seen=datetime.now(tz=UTC),
                ip_address=ip_address,
            )
            .on_conflict_do_update(
                index_elements=["receiver_id"],
                set_={
                    "last_seen": datetime.now(tz=UTC),
                    "ip_address": ip_address,
                },
            )
        )
        await session.execute(stmt)
        await session.commit()
