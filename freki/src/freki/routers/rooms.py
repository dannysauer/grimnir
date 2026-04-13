"""
routers/rooms.py

GET    /api/rooms             list all rooms ordered by floor, name
POST   /api/rooms             create a room
PATCH  /api/rooms/{name}      update name and/or floor
                              (name change cascades to labels via FK; also
                               updates csi_samples.label which has no FK)
DELETE /api/rooms/{name}      delete a room (409 if labels reference it)
"""

from __future__ import annotations

from datetime import datetime

from csi_models import CsiSample, Room
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..db import SessionDep

router = APIRouter()


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


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=list[RoomOut])
async def list_rooms(session: SessionDep):
    result = await session.execute(
        select(Room).order_by(Room.floor.asc(), Room.name.asc())
    )
    return result.scalars().all()


@router.post("", response_model=RoomOut, status_code=201)
async def create_room(body: RoomCreate, session: SessionDep):
    room = Room(name=body.name, floor=body.floor)
    session.add(room)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"Room '{body.name}' already exists")
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
        raise HTTPException(status_code=409, detail=f"Room '{body.name}' already exists")

    # labels.room is updated automatically by the FK ON UPDATE CASCADE.
    # csi_samples.label has no FK, so update it explicitly.
    if new_name != old_name:
        await session.execute(
            update(CsiSample)
            .where(CsiSample.label == old_name)
            .values(label=new_name)
        )

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
        )
