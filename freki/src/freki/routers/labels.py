"""
routers/labels.py

GET    /api/labels?minutes=120   recent labels
POST   /api/labels               create a label (also backfills csi_samples.label)
DELETE /api/labels/{id}          delete a label (also clears backfilled labels)
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from ..db import get_pool

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
        if not v.strip():
            raise ValueError("room must not be empty")
        return v.strip()

    @field_validator("time_end")
    @classmethod
    def end_after_start(cls, v: datetime, info) -> datetime:
        if "time_start" in info.data and v <= info.data["time_start"]:
            raise ValueError("time_end must be after time_start")
        return v


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("")
async def list_labels(minutes: int = 120):
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id, time_start, time_end, room, occupants, notes, created_at
        FROM labels
        WHERE time_end > NOW() - ($1 || ' minutes')::INTERVAL
        ORDER BY time_start DESC
        """,
        str(minutes),
    )
    return [
        {
            "id":         row["id"],
            "time_start": row["time_start"].isoformat(),
            "time_end":   row["time_end"].isoformat(),
            "room":       row["room"],
            "occupants":  row["occupants"],
            "notes":      row["notes"],
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]


@router.post("", status_code=201)
async def create_label(body: LabelCreate):
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO labels (time_start, time_end, room, occupants, notes)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id, created_at
                """,
                body.time_start,
                body.time_end,
                body.room,
                body.occupants,
                body.notes,
            )

            # Backfill label onto csi_samples in this window
            await conn.execute(
                """
                UPDATE csi_samples
                SET label = $1
                WHERE time >= $2 AND time < $3
                """,
                body.room,
                body.time_start,
                body.time_end,
            )

    return {
        "id":         row["id"],
        "created_at": row["created_at"].isoformat(),
    }


@router.delete("/{label_id}", status_code=204)
async def delete_label(label_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "DELETE FROM labels WHERE id = $1 RETURNING time_start, time_end, room",
                label_id,
            )
            if not row:
                raise HTTPException(status_code=404, detail="Label not found")

            # Clear the label from samples that were tagged by this label
            await conn.execute(
                """
                UPDATE csi_samples
                SET label = NULL
                WHERE time >= $1 AND time < $2 AND label = $3
                """,
                row["time_start"],
                row["time_end"],
                row["room"],
            )
