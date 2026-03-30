"""
routers/history.py

GET /api/history/variance?receiver_id=1&minutes=60
    Per-minute RSSI variance from the continuous aggregate.
    Used by the 60-minute variance chart on the dashboard.

GET /api/history/snapshot?receiver_id=1&limit=1
    Most recent raw CSI samples for a receiver.
    Used by the subcarrier amplitude heatmap.

GET /api/history/receivers
    All receivers with heartbeat data.
    Used by the dashboard on initial load.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select, text

from csi_models import CsiSample, Receiver, ReceiverHeartbeat

from ..db import SessionDep

router = APIRouter()


@router.get("/variance")
async def get_variance(
    session: SessionDep,
    receiver_id: int = Query(...),
    minutes: int = Query(default=60, ge=1, le=1440),
):
    """
    Query the csi_variance_1min continuous aggregate.
    Falls back to raw csi_samples if the aggregate has no data yet
    (e.g. immediately after first startup).
    """
    result = await session.execute(
        text(
            """
            SELECT
                bucket AS time,
                avg_rssi,
                stddev_rssi,
                sample_count
            FROM csi_variance_1min
            WHERE receiver_id = :rx_id
              AND bucket >= NOW() - (:minutes || ' minutes')::INTERVAL
            ORDER BY bucket ASC
            """
        ),
        {"rx_id": receiver_id, "minutes": minutes},
    )
    rows = result.mappings().all()

    # Fall back to raw data if aggregate is empty (< 2 minutes of data)
    if len(rows) < 2:
        result = await session.execute(
            text(
                """
                SELECT
                    time_bucket('1 minute', time) AS time,
                    AVG(rssi)::float              AS avg_rssi,
                    STDDEV(rssi)::float           AS stddev_rssi,
                    COUNT(*)                      AS sample_count
                FROM csi_samples
                WHERE receiver_id = :rx_id
                  AND time >= NOW() - (:minutes || ' minutes')::INTERVAL
                GROUP BY 1
                ORDER BY 1 ASC
                """
            ),
            {"rx_id": receiver_id, "minutes": minutes},
        )
        rows = result.mappings().all()

    return [
        {
            "time": row["time"].isoformat(),
            "avg_rssi": round(row["avg_rssi"], 1) if row["avg_rssi"] is not None else None,
            "stddev_rssi": round(row["stddev_rssi"], 3) if row["stddev_rssi"] is not None else None,
            "sample_count": row["sample_count"],
        }
        for row in rows
    ]


@router.get("/snapshot")
async def get_snapshot(
    session: SessionDep,
    receiver_id: int = Query(...),
    limit: int = Query(default=1, ge=1, le=50),
):
    """Most recent CSI samples for a receiver — used for the amplitude heatmap."""
    result = await session.execute(
        select(CsiSample)
        .where(CsiSample.receiver_id == receiver_id)
        .order_by(CsiSample.time.desc())
        .limit(limit)
    )
    samples = result.scalars().all()

    return [
        {
            "time": s.time.isoformat(),
            "rssi": s.rssi,
            "antenna_count": s.antenna_count,
            "subcarrier_count": s.subcarrier_count,
            "amplitude": s.amplitude,
            "phase": s.phase,
            "label": s.label,
        }
        for s in samples
    ]


@router.get("/receivers")
async def get_receivers(session: SessionDep):
    """All receivers with heartbeat — used by the dashboard on load."""
    result = await session.execute(
        select(Receiver, ReceiverHeartbeat)
        .outerjoin(ReceiverHeartbeat, Receiver.id == ReceiverHeartbeat.receiver_id)
        .order_by(Receiver.id)
    )
    rows = result.all()

    return [
        {
            "id": r.id,
            "name": r.name,
            "mac": str(r.mac),
            "floor": r.floor,
            "location": r.location,
            "role": r.role,
            "active": r.active,
            "last_seen": h.last_seen.isoformat() if h else None,
            "ip_address": str(h.ip_address) if h and h.ip_address else None,
        }
        for r, h in rows
    ]
