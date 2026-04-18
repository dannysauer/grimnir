"""
routers/predictions.py

PUT /api/predictions/current   — Völva pushes latest room occupancy JSON here
GET /api/predictions/current   — Home Assistant polls this for the current state
GET /api/predictions/stream    — SSE of live predictions for the web view

State is held in Postgres so every Freki replica serves the same current
prediction. SSE subscribers poll the shared row and emit whenever it changes.

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

from csi_models import CurrentPrediction, get_session_factory
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ..db import SessionDep

router = APIRouter()

PREDICTION_ROW_ID = 1
STREAM_POLL_INTERVAL_S = 1.0
STREAM_KEEPALIVE_S = 15.0


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class RoomPrediction(BaseModel):
    human_count: int = Field(ge=0)


class PredictionUpdate(BaseModel):
    timestamp: datetime
    model_id: int
    rooms: dict[str, RoomPrediction] = Field(min_length=1)


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.put("/current", status_code=204)
async def put_current(body: PredictionUpdate, session: SessionDep):
    payload = body.model_dump(mode="json")
    stmt = (
        insert(CurrentPrediction)
        .values(id=PREDICTION_ROW_ID, payload=payload)
        .on_conflict_do_update(
            index_elements=[CurrentPrediction.id],
            set_={
                "payload": payload,
                "updated_at": func.now(),
            },
        )
    )
    await session.execute(stmt)
    await session.commit()


@router.get("/current", response_model=PredictionUpdate)
async def get_current(session: SessionDep):
    row = await session.execute(
        select(CurrentPrediction.payload).where(CurrentPrediction.id == PREDICTION_ROW_ID)
    )
    snapshot = row.scalar_one_or_none()
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
    factory = get_session_factory()
    last_updated_at: datetime | None = None
    last_keepalive_at = datetime.now(tz=UTC)
    try:
        while True:
            async with factory() as session:
                row = await session.execute(
                    select(CurrentPrediction.payload, CurrentPrediction.updated_at).where(
                        CurrentPrediction.id == PREDICTION_ROW_ID
                    )
                )
                snapshot = row.one_or_none()

            if snapshot is not None and snapshot.updated_at != last_updated_at:
                last_updated_at = snapshot.updated_at
                last_keepalive_at = datetime.now(tz=UTC)
                yield f"data: {json.dumps(snapshot.payload)}\n\n"
                continue

            now = datetime.now(tz=UTC)
            if (now - last_keepalive_at).total_seconds() >= STREAM_KEEPALIVE_S:
                last_keepalive_at = now
                yield f": keepalive {now.isoformat()}\n\n"
                continue

            await asyncio.sleep(STREAM_POLL_INTERVAL_S)
    except asyncio.CancelledError:
        pass
