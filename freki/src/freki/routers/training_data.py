"""
routers/training_data.py

GET /api/training-data  — cursor-paginated bulk export of labeled CSI samples.

Queries the ``training_samples`` hypertable (materialized on label create by
`labels.py`). Nornir loops until `next_cursor` is null. Freki memory stays flat
because each page is bounded by ``page_size`` and the query uses the unique
``(time, receiver_id)`` index for efficient seek-paging.

Query params
------------
time_start : ISO-8601, required
time_end   : ISO-8601, required; must be > time_start
rooms      : comma-separated list, 1..32 entries
cursor     : opaque base64 string returned by the previous page, or omitted
page_size  : 1..5000 (default 500)

Response envelope
-----------------
    {"rows": [...], "next_cursor": "..." | null}

Rows match the columns needed for feature extraction; the per-label human
count (``labels.occupants``) is NOT included — clients fetch labels metadata
separately via ``GET /api/labels``.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Annotated

from csi_models import TrainingSample
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, tuple_

from ..db import SessionDep

router = APIRouter()

DEFAULT_PAGE_SIZE = 500
MAX_PAGE_SIZE = 5000
MAX_ROOMS = 32


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class TrainingSampleOut(BaseModel):
    time: datetime
    receiver_id: int
    transmitter_mac: str
    rssi: int
    channel: int
    bandwidth: int
    antenna_count: int
    subcarrier_count: int
    amplitude: list[float]
    phase: list[float]
    label: str

    model_config = {"from_attributes": True}


class TrainingDataPage(BaseModel):
    rows: list[TrainingSampleOut]
    next_cursor: str | None


# ── Cursor helpers ────────────────────────────────────────────────────────────


def _encode_cursor(time: datetime, receiver_id: int) -> str:
    payload = json.dumps({"t": time.isoformat(), "r": receiver_id}).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        payload = base64.urlsafe_b64decode(cursor.encode("ascii"))
        obj = json.loads(payload)
        return datetime.fromisoformat(obj["t"]), int(obj["r"])
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid cursor: {exc}") from exc


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.get("", response_model=TrainingDataPage)
async def get_training_data(
    session: SessionDep,
    time_start: datetime,
    time_end: datetime,
    rooms: Annotated[str, Query(min_length=1)],
    cursor: str | None = None,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
):
    if time_end <= time_start:
        raise HTTPException(status_code=422, detail="time_end must be after time_start")

    room_list = [r.strip() for r in rooms.split(",") if r.strip()]
    if not room_list:
        raise HTTPException(status_code=422, detail="rooms must not be empty")
    if len(room_list) > MAX_ROOMS:
        raise HTTPException(status_code=422, detail=f"rooms must have at most {MAX_ROOMS} entries")

    stmt = (
        select(TrainingSample)
        .where(
            TrainingSample.time >= time_start,
            TrainingSample.time < time_end,
            TrainingSample.label.in_(room_list),
        )
        .order_by(TrainingSample.time.asc(), TrainingSample.receiver_id.asc())
        .limit(page_size + 1)  # overshoot by one so we can detect "has more"
    )

    if cursor is not None:
        cursor_time, cursor_receiver_id = _decode_cursor(cursor)
        stmt = stmt.where(
            tuple_(TrainingSample.time, TrainingSample.receiver_id)
            > tuple_(cursor_time, cursor_receiver_id)
        )

    result = await session.execute(stmt)
    samples = result.scalars().all()

    has_more = len(samples) > page_size
    page = samples[:page_size]
    next_cursor = _encode_cursor(page[-1].time, page[-1].receiver_id) if has_more and page else None

    return TrainingDataPage(
        rows=[TrainingSampleOut.model_validate(s) for s in page],
        next_cursor=next_cursor,
    )
