"""
routers/labels.py

GET    /api/labels?minutes=120   recent labels
POST   /api/labels               create a label (also backfills csi_samples.label)
DELETE /api/labels/{id}          delete a label (also clears backfilled labels)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from csi_models import CsiSample, Label, get_session_factory
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from ..db import SessionDep
from ..training_samples_access import is_training_samples_permission_error

router = APIRouter()
log = structlog.get_logger(__name__)

BACKFILL_LOCK_TIMEOUT = "2s"
BACKFILL_STATEMENT_TIMEOUT = "15s"


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


async def _insert_training_samples_for_window(
    session: SessionDep,
    start: datetime,
    end: datetime,
) -> None:
    await _set_backfill_timeouts(session)
    await session.execute(
        text("""
            INSERT INTO training_samples
            SELECT time, receiver_id, transmitter_mac, rssi, noise_floor,
                   channel, bandwidth, antenna_count, subcarrier_count,
                   amplitude, phase, raw_bytes, label
            FROM csi_samples
            WHERE time >= :start AND time < :end AND label IS NOT NULL
            ON CONFLICT (time, receiver_id) DO UPDATE SET label = EXCLUDED.label
        """),
        {"start": start, "end": end},
    )


async def _set_backfill_timeouts(session: SessionDep) -> None:
    await session.execute(text(f"SET LOCAL lock_timeout = '{BACKFILL_LOCK_TIMEOUT}'"))
    await session.execute(text(f"SET LOCAL statement_timeout = '{BACKFILL_STATEMENT_TIMEOUT}'"))


async def _backfill_csi_samples_best_effort(
    session: SessionDep,
    start: datetime,
    end: datetime,
    room: str,
) -> bool:
    try:
        await _set_backfill_timeouts(session)
        await session.execute(
            update(CsiSample)
            .where(
                CsiSample.time >= start,
                CsiSample.time < end,
            )
            .values(label=room)
        )
        await session.commit()
        return True
    except DBAPIError as exc:
        await session.rollback()
        log.warning(
            "csi_samples.backfill_skipped",
            reason="db_error",
            error=str(exc.orig),
            start=start.isoformat(),
            end=end.isoformat(),
            room=room,
        )
        return False


async def _backfill_label_best_effort(
    label_id: int,
    start: datetime,
    end: datetime,
    room: str,
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        backfilled = await _backfill_csi_samples_best_effort(session, start, end, room)
        if not backfilled:
            return
        await _sync_training_samples_best_effort(session, start, end)
        log.info(
            "label.backfill_completed",
            label_id=label_id,
            start=start.isoformat(),
            end=end.isoformat(),
            room=room,
        )


async def _sync_training_samples_best_effort(
    session: SessionDep,
    start: datetime,
    end: datetime,
) -> None:
    try:
        await _insert_training_samples_for_window(session, start, end)
        await session.commit()
    except DBAPIError as exc:
        await session.rollback()
        if not is_training_samples_permission_error(exc):
            raise
        log.warning(
            "training_samples.sync_skipped",
            reason="permission_denied",
            start=start.isoformat(),
            end=end.isoformat(),
        )


async def _resync_training_samples_best_effort(
    session: SessionDep,
    start: datetime,
    end: datetime,
) -> None:
    try:
        await _set_backfill_timeouts(session)
        await session.execute(
            text("DELETE FROM training_samples WHERE time >= :start AND time < :end"),
            {"start": start, "end": end},
        )
        await _insert_training_samples_for_window(session, start, end)
        await session.commit()
    except DBAPIError as exc:
        await session.rollback()
        if not is_training_samples_permission_error(exc):
            raise
        log.warning(
            "training_samples.resync_skipped",
            reason="permission_denied",
            start=start.isoformat(),
            end=end.isoformat(),
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=list[LabelOut])
async def list_labels(session: SessionDep, minutes: int = 120):
    cutoff = datetime.now(tz=UTC) - timedelta(minutes=minutes)
    result = await session.execute(
        select(Label).where(Label.time_end >= cutoff).order_by(Label.time_start.desc())
    )
    return result.scalars().all()


@router.post("", response_model=LabelOut, status_code=201)
async def create_label(body: LabelCreate, background_tasks: BackgroundTasks, session: SessionDep):
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
        ) from None

    await session.commit()
    await session.refresh(label)
    response = LabelOut.model_validate(label)
    background_tasks.add_task(
        _backfill_label_best_effort,
        label.id,
        body.time_start,
        body.time_end,
        body.room,
    )
    return response


@router.delete("/{label_id}", status_code=204)
async def delete_label(label_id: int, session: SessionDep):
    result = await session.execute(select(Label).where(Label.id == label_id))
    label = result.scalar_one_or_none()
    if label is None:
        raise HTTPException(status_code=404, detail="Label not found")
    window_start = label.time_start
    window_end = label.time_end

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

    # Sync training_samples: clear the deleted window, then re-add whatever
    # survived (from overlapping labels re-applied to csi_samples above).
    await session.commit()
    await _resync_training_samples_best_effort(session, window_start, window_end)
