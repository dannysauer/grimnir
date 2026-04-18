"""
routers/csi_stream.py

GET /api/csi-stream — SSE tail of raw CSI rows landing in ``csi_samples``.

Völva (and any other live consumer that needs raw amplitude/phase arrays)
subscribes to this stream. The existing ``/api/stream`` endpoint emits only
per-receiver summary stats and is not suitable for inference — see review B1.

Each cycle (every ``CSI_STREAM_INTERVAL_MS`` ms, default 200 ms) this endpoint
polls for rows with ``(time, receiver_id) > cursor`` up to ``MAX_BATCH`` rows
and emits each as a separate SSE event. The cursor advances to the last
emitted row. When a consumer falls too far behind (i.e. the query would return
more than ``MAX_BATCH`` rows), rows older than the batch tail are dropped —
live inference doesn't benefit from catch-up.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime

from csi_models import CsiSample, get_session_factory
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy import select, tuple_

router = APIRouter()

INTERVAL_MS = int(os.environ.get("CSI_STREAM_INTERVAL_MS", "200"))
MAX_BATCH = int(os.environ.get("CSI_STREAM_MAX_BATCH", "200"))


def _serialize(row: CsiSample) -> str:
    payload = {
        "time": row.time.isoformat(),
        "receiver_id": row.receiver_id,
        "transmitter_mac": row.transmitter_mac,
        "rssi": row.rssi,
        "noise_floor": row.noise_floor,
        "channel": row.channel,
        "bandwidth": row.bandwidth,
        "antenna_count": row.antenna_count,
        "subcarrier_count": row.subcarrier_count,
        "amplitude": list(row.amplitude),
        "phase": list(row.phase),
        "label": row.label,
    }
    return f"data: {json.dumps(payload)}\n\n"


async def _latest_cursor() -> tuple[datetime, int] | None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(CsiSample.time, CsiSample.receiver_id)
            .order_by(CsiSample.time.desc(), CsiSample.receiver_id.desc())
            .limit(1)
        )
        row = result.first()
    if row is None:
        return None
    return row.time, row.receiver_id


KEEPALIVE_IDLE_S = 15.0


async def _event_generator():
    factory = get_session_factory()
    interval_s = max(INTERVAL_MS, 50) / 1000.0

    # Start at the current tail so we don't replay history on connect.
    cursor = await _latest_cursor()
    loop = asyncio.get_event_loop()
    last_emit = loop.time()

    try:
        while True:
            if cursor is None:
                # Table was empty on connect; keep looking for the first row.
                cursor = await _latest_cursor()
            else:
                async with factory() as session:
                    stmt = (
                        select(CsiSample)
                        .where(tuple_(CsiSample.time, CsiSample.receiver_id) > tuple_(*cursor))
                        .order_by(CsiSample.time.asc(), CsiSample.receiver_id.asc())
                        .limit(MAX_BATCH)
                    )
                    rows = (await session.execute(stmt)).scalars().all()
                for row in rows:
                    yield _serialize(row)
                    cursor = (row.time, row.receiver_id)
                if rows:
                    last_emit = loop.time()

            if loop.time() - last_emit >= KEEPALIVE_IDLE_S:
                yield f": tail {datetime.now(tz=UTC).isoformat()}\n\n"
                last_emit = loop.time()

            await asyncio.sleep(interval_s)
    except asyncio.CancelledError:
        pass


@router.get("")
async def csi_stream():
    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
