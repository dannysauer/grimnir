"""
routers/predictions.py

PUT /api/predictions/current   — Völva pushes latest room occupancy JSON here
GET /api/predictions/current   — Home Assistant polls this for the current state
GET /api/predictions/stream    — SSE of live predictions for the web view

State is held in process memory. There is exactly one active prediction at a
time; on restart the cache is empty until Völva pushes a fresh payload.

Response shape (mirrors issue #19):
    {
      "timestamp": "2026-04-17T12:00:00Z",
      "model_id": 3,
      "rooms": {"kitchen": {"human_count": 1}, ...}
    }
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter()


# ── In-process state ──────────────────────────────────────────────────────────

_state_lock = asyncio.Lock()
_latest: dict | None = None
_subscribers: set[asyncio.Queue[dict]] = set()


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class RoomPrediction(BaseModel):
    human_count: int = Field(ge=0)


class PredictionUpdate(BaseModel):
    timestamp: datetime
    model_id: int
    rooms: dict[str, RoomPrediction] = Field(min_length=1)


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.put("/current", status_code=204)
async def put_current(body: PredictionUpdate):
    global _latest
    payload = body.model_dump(mode="json")
    async with _state_lock:
        _latest = payload
        dead: list[asyncio.Queue[dict]] = []
        for queue in _subscribers:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(queue)
        for queue in dead:
            _subscribers.discard(queue)


@router.get("/current", response_model=PredictionUpdate)
async def get_current():
    async with _state_lock:
        snapshot = _latest
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No prediction available")
    return snapshot


@router.get("/stream")
async def stream_predictions():
    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _event_generator():
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=32)
    async with _state_lock:
        _subscribers.add(queue)
        initial = _latest
    try:
        if initial is not None:
            yield f"data: {json.dumps(initial)}\n\n"
        keepalive = 15.0
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=keepalive)
                yield f"data: {json.dumps(payload)}\n\n"
            except TimeoutError:
                # SSE comment frame — keeps intermediaries from timing the
                # connection out during quiet periods.
                now = datetime.now(tz=UTC).isoformat()
                yield f": keepalive {now}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        async with _state_lock:
            _subscribers.discard(queue)
