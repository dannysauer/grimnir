"""
routers/labels.py

GET    /api/labels?minutes=120   recent labels
POST   /api/labels               create a label (also backfills csi_samples.label)
DELETE /api/labels/{id}          delete a label (also clears backfilled labels)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from csi_models import CsiSample, Label
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..db import SessionDep

router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class LabelCreate(BaseModel):
    time_start: datetime
    time_end: datetime
    room: str
    occupants: int = 1
    notes: str | None = None

    @field_validator("room")
    @classmethod
    def room_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("room must not be empty")
        return v

    @model_validator(mode="after")
    def end_after_start(self) -> LabelCreate:
        if self.time_end <= self.time_start:
            raise ValueError("time_end must be after time_start")
        return self


class LabelOut(BaseModel):
    id: int
    time_start: datetime
    time_end: datetime
    room: str
    occupants: int
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=list[LabelOut])
async def list_labels(session: SessionDep, minutes: int = 120):
    cutoff = datetime.now(tz=UTC) - timedelta(minutes=minutes)
    result = await session.execute(
        select(Label).where(Label.time_end >= cutoff).order_by(Label.time_start.desc())
    )
    return result.scalars().all()


@router.post("", response_model=LabelOut, status_code=201)
async def create_label(body: LabelCreate, session: SessionDep):
    label = Label(
        time_start=body.time_start,
        time_end=body.time_end,
        room=body.room,
        occupants=body.occupants,
        notes=body.notes,
    )
    session.add(label)
    try:
        await session.flush()  # get label.id before backfill
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=422,
            detail=f"Room '{body.room}' does not exist — add it via manage rooms first",
        )

    # Backfill csi_samples.label for this time window
    await session.execute(
        update(CsiSample)
        .where(
            CsiSample.time >= body.time_start,
            CsiSample.time < body.time_end,
        )
        .values(label=body.room)
    )

    await session.commit()
    await session.refresh(label)
    return label


@router.delete("/{label_id}", status_code=204)
async def delete_label(label_id: int, session: SessionDep):
    result = await session.execute(select(Label).where(Label.id == label_id))
    label = result.scalar_one_or_none()
    if label is None:
        raise HTTPException(status_code=404, detail="Label not found")

    # Clear labels in the deleted window, then re-apply any surviving
    # overlapping labels so deleting one label does not erase another.
    await session.execute(
        update(CsiSample)
        .where(
            CsiSample.time >= label.time_start,
            CsiSample.time < label.time_end,
        )
        .values(label=None)
    )

    await session.delete(label)
    await session.flush()

    overlapping_result = await session.execute(
        select(Label)
        .where(
            Label.time_start < label.time_end,
            Label.time_end > label.time_start,
        )
        .order_by(Label.time_start.asc(), Label.created_at.asc(), Label.id.asc())
    )

    for overlapping_label in overlapping_result.scalars():
        overlap_start = max(label.time_start, overlapping_label.time_start)
        overlap_end = min(label.time_end, overlapping_label.time_end)
        await session.execute(
            update(CsiSample)
            .where(
                CsiSample.time >= overlap_start,
                CsiSample.time < overlap_end,
            )
            .values(label=overlapping_label.room)
        )

    await session.commit()
