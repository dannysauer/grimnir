"""
routers/training_daemons.py

GET  /api/training-daemons           list registered Nornir daemons
POST /api/training-daemons/heartbeat upsert a daemon by name and bump last_seen

Daemons (Nornir instances) call the heartbeat endpoint on startup and on a
configurable interval; Hlidskjalf lists them to show which daemons are online.
"""

from __future__ import annotations

from datetime import datetime

from csi_models import TrainingDaemon
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ..db import SessionDep
from ..ml_auth import require_ml_control_secret

router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class DaemonHeartbeat(BaseModel):
    name: str
    host: str
    ip_address: str | None = None
    capabilities: dict = Field(default_factory=dict)


class DaemonOut(BaseModel):
    id: int
    name: str
    host: str
    ip_address: str | None
    capabilities: dict
    last_seen: datetime
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("ip_address", mode="before")
    @classmethod
    def stringify_ip_address(cls, value: object) -> object:
        return str(value) if value is not None else None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=list[DaemonOut])
async def list_daemons(session: SessionDep):
    result = await session.execute(select(TrainingDaemon).order_by(TrainingDaemon.name.asc()))
    return [DaemonOut.model_validate(daemon) for daemon in result.scalars().all()]


@router.post("/heartbeat", response_model=DaemonOut)
async def heartbeat(
    body: DaemonHeartbeat,
    session: SessionDep,
    _: None = Depends(require_ml_control_secret),
):
    stmt = (
        insert(TrainingDaemon)
        .values(
            name=body.name,
            host=body.host,
            ip_address=body.ip_address,
            capabilities=body.capabilities,
        )
        .on_conflict_do_update(
            index_elements=["name"],
            set_={
                "host": body.host,
                "ip_address": body.ip_address,
                "capabilities": body.capabilities,
                "last_seen": func.now(),
            },
        )
        .returning(TrainingDaemon)
    )
    result = await session.execute(stmt)
    daemon = result.scalar_one()
    await session.commit()
    return DaemonOut.model_validate(daemon)
