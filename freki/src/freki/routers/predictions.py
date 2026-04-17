"""
routers/predictions.py

PUT /api/predictions/current   Völva pushes latest predictions (in-memory store)
GET /api/predictions/current   return latest predictions as JSON
GET /api/predictions/stream    SSE stream of live predictions
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()

# In-memory store — reset on Freki restart. Predictions are ephemeral.
_current: dict[str, Any] = {}
_updated = asyncio.Event()


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class PredictionUpdate(BaseModel):
    timestamp: datetime
    model_id: int
    rooms: dict[str, dict[str, int]]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.put("/current", status_code=204)
async def push_predictions(body: PredictionUpdate):
    """Völva calls this to update the current prediction state."""
    global _current
    _current = body.model_dump(mode="json")
    _updated.set()
    _updated.clear()


@router.get("/current")
async def get_predictions():
    """Return latest predictions as JSON (for Home Assistant REST sensor)."""
    return _current


async def _sse_generator() -> AsyncGenerator[str, None]:
    while True:
        if _current:
            yield f"data: {json.dumps(_current)}\n\n"
        try:
            await asyncio.wait_for(_updated.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass


@router.get("/stream")
async def stream_predictions():
    """SSE stream of live predictions."""
    return StreamingResponse(
        _sse_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
