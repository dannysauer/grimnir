"""
routers/stream.py

GET /api/stream  — Server-Sent Events

Pushes a JSON snapshot every second containing:
  - all active receivers with last RSSI, variance, and liveness
  - server timestamp

The frontend uses this to update receiver cards and the variance chart in
real time without polling.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text

from csi_models import Receiver, ReceiverHeartbeat, get_session_factory
from ..metrics import sse_connections_active

router = APIRouter()

POLL_INTERVAL_S = 1.0
WINDOW_S = 30  # look back this many seconds for recent RSSI stats


async def _fetch_snapshot() -> dict:
    factory = get_session_factory()
    since = datetime.now(tz=timezone.utc) - timedelta(seconds=WINDOW_S)

    async with factory() as session:
        # All active receivers with their heartbeat
        result = await session.execute(
            select(Receiver, ReceiverHeartbeat)
            .outerjoin(ReceiverHeartbeat, Receiver.id == ReceiverHeartbeat.receiver_id)
            .where(Receiver.active == True)
            .order_by(Receiver.id)
        )
        rows = result.all()

        # Recent RSSI stats per receiver from csi_samples
        # Using raw SQL for the aggregation — cleaner than ORM for window queries
        stats_result = await session.execute(
            text(
                """
                SELECT
                    receiver_id,
                    AVG(rssi)::float          AS avg_rssi,
                    STDDEV(rssi)::float       AS stddev_rssi,
                    COUNT(*)                  AS sample_count
                FROM csi_samples
                WHERE time >= :since
                GROUP BY receiver_id
                """
            ),
            {"since": since},
        )
        stats = {row.receiver_id: row for row in stats_result}

    receivers = []
    for receiver, heartbeat in rows:
        s = stats.get(receiver.id)
        receivers.append(
            {
                "id": receiver.id,
                "name": receiver.name,
                "floor": receiver.floor,
                "location": receiver.location,
                "role": receiver.role,
                "last_seen": heartbeat.last_seen.isoformat() if heartbeat else None,
                "ip_address": str(heartbeat.ip_address) if heartbeat and heartbeat.ip_address else None,
                "avg_rssi": round(s.avg_rssi, 1) if s and s.avg_rssi is not None else None,
                "stddev_rssi": round(s.stddev_rssi, 3) if s and s.stddev_rssi is not None else None,
                "sample_count": s.sample_count if s else 0,
            }
        )

    return {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "window_s": WINDOW_S,
        "receivers": receivers,
    }


async def _event_generator():
    sse_connections_active.inc()
    try:
        while True:
            try:
                payload = await _fetch_snapshot()
                yield f"data: {json.dumps(payload)}\n\n"
            except Exception as exc:
                yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"
            await asyncio.sleep(POLL_INTERVAL_S)
    except asyncio.CancelledError:
        pass
    finally:
        sse_connections_active.dec()


@router.get("/stream")
async def stream():
    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
