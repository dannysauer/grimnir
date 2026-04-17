"""
routers/training_data.py

GET /api/training-data   streaming NDJSON export of labeled CSI samples

Query params:
  time_start  ISO-8601 datetime (required)
  time_end    ISO-8601 datetime (required)
  rooms       comma-separated room names (optional; omit for all rooms)

Each line of the response is a JSON object with fields:
  time, receiver_id, transmitter_mac, rssi, noise_floor, channel, bandwidth,
  antenna_count, subcarrier_count, amplitude, phase, label
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import datetime

from csi_models import CsiSample
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ..db import SessionDep

router = APIRouter()


async def _stream_samples(
    session: SessionDep,
    time_start: datetime,
    time_end: datetime,
    rooms: list[str] | None,
) -> AsyncGenerator[str, None]:
    stmt = (
        select(CsiSample)
        .where(CsiSample.time >= time_start, CsiSample.time < time_end)
        .where(CsiSample.label.is_not(None))
        .order_by(CsiSample.time.asc())
    )
    if rooms:
        stmt = stmt.where(CsiSample.label.in_(rooms))

    result = await session.stream_scalars(stmt)
    async for sample in result:
        yield json.dumps(
            {
                "time": sample.time.isoformat(),
                "receiver_id": sample.receiver_id,
                "transmitter_mac": sample.transmitter_mac,
                "rssi": sample.rssi,
                "noise_floor": sample.noise_floor,
                "channel": sample.channel,
                "bandwidth": sample.bandwidth,
                "antenna_count": sample.antenna_count,
                "subcarrier_count": sample.subcarrier_count,
                "amplitude": sample.amplitude,
                "phase": sample.phase,
                "label": sample.label,
            }
        ) + "\n"


@router.get("")
async def stream_training_data(
    session: SessionDep,
    time_start: datetime = Query(...),
    time_end: datetime = Query(...),
    rooms: str | None = Query(default=None, description="Comma-separated room names"),
):
    """Stream labeled CSI samples as NDJSON for Nornir training data access."""
    room_list = [r.strip() for r in rooms.split(",")] if rooms else None
    return StreamingResponse(
        _stream_samples(session, time_start, time_end, room_list),
        media_type="application/x-ndjson",
        headers={"X-Accel-Buffering": "no"},
    )
