"""
routers/rooms.py

GET    /api/rooms             list all rooms ordered by floor, name
POST   /api/rooms             create a room
PATCH  /api/rooms/{name}      update name and/or floor
                              (name change cascades to labels via FK; also
                               rewrites csi_samples.label and
                               training_samples.label, which have no FK)
DELETE /api/rooms/{name}      delete a room (409 if labels reference it)
"""

from __future__ import annotations

from datetime import datetime

import structlog
from csi_models import CsiSample, Room
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionDep
from ..training_samples_access import is_training_samples_permission_error

router = APIRouter()
log = structlog.get_logger(__name__)


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class RoomOut(BaseModel):
    name: str
    floor: int
    created_at: datetime

    model_config = {"from_attributes": True}


class RoomCreate(BaseModel):
    name: str
    floor: int = 0

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v


class RoomUpdate(BaseModel):
    name: str | None = None
    floor: int | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("name must not be empty")
        return v


async def _rename_training_samples_label(
    session: AsyncSession, old_name: str, new_name: str
) -> None:
    """Propagate a room rename to the denormalized training_samples.label.

    Runs inside the caller's transaction under a savepoint, so a real
    failure aborts the whole rename instead of leaving the tables split
    between two names. Installs where training_samples is owned by a
    different role (#34/#37) skip the sync with a warning so the rename
    itself still succeeds.
    """
    try:
        async with session.begin_nested():
            await session.execute(
                text("UPDATE training_samples SET label = :new_name WHERE label = :old_name"),
                {"new_name": new_name, "old_name": old_name},
            )
    except DBAPIError as exc:
        if not is_training_samples_permission_error(exc):
            raise
        log.warning(
            "training_samples.rename_skipped",
            reason="permission_denied",
            old_name=old_name,
            new_name=new_name,
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=list[RoomOut])
async def list_rooms(session: SessionDep):
    result = await session.execute(select(Room).order_by(Room.floor.asc(), Room.name.asc()))
    return result.scalars().all()


@router.post("", response_model=RoomOut, status_code=201)
async def create_room(body: RoomCreate, session: SessionDep):
    room = Room(name=body.name, floor=body.floor)
    session.add(room)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"Room '{body.name}' already exists") from None
    await session.refresh(room)
    return room


@router.patch("/{room_name}", response_model=RoomOut)
async def update_room(room_name: str, body: RoomUpdate, session: SessionDep):
    result = await session.execute(select(Room).where(Room.name == room_name))
    room = result.scalar_one_or_none()
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")

    old_name = room.name
    new_name = body.name if body.name is not None else old_name

    if body.name is not None:
        room.name = body.name
    if body.floor is not None:
        room.floor = body.floor

    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"Room '{body.name}' already exists") from None

    # labels.room is updated automatically by the FK ON UPDATE CASCADE.
    # csi_samples.label and training_samples.label have no FK, so update
    # them explicitly — training_samples is what Nornir trains from, so a
    # rename that skips it silently orphans that room's training data.
    if new_name != old_name:
        await session.execute(
            update(CsiSample).where(CsiSample.label == old_name).values(label=new_name)
        )
        await _rename_training_samples_label(session, old_name, new_name)

    await session.commit()

    # Re-query by new name (PK may have changed if name changed).
    result = await session.execute(select(Room).where(Room.name == new_name))
    return result.scalar_one()


@router.delete("/{room_name}", status_code=204)
async def delete_room(room_name: str, session: SessionDep):
    result = await session.execute(select(Room).where(Room.name == room_name))
    room = result.scalar_one_or_none()
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")

    await session.delete(room)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Room '{room_name}' has existing labels and cannot be deleted",
        ) from None
