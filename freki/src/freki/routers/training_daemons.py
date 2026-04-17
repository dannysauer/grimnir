"""
routers/training_daemons.py

POST /api/training-daemons/heartbeat   register or update a Nornir daemon
GET  /api/training-daemons             list all daemons with last-seen
"""

from __future__ import annotations

import socket
from datetime import datetime

from csi_models import TrainingDaemon
from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select, update

from ..db import SessionDep

router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class DaemonHeartbeat(BaseModel):
    name: str
    host: str
    capabilities: dict = {}


class DaemonOut(BaseModel):
    id: int
    name: str
    host: str
    ip_address: str | None
    capabilities: dict
    last_seen: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/heartbeat", response_model=DaemonOut)
async def daemon_heartbeat(body: DaemonHeartbeat, request: Request, session: SessionDep):
    """Upsert daemon registration and update last_seen timestamp."""
    ip = request.client.host if request.client else None

    result = await session.execute(
        select(TrainingDaemon).where(TrainingDaemon.name == body.name)
    )
    daemon = result.scalar_one_or_none()

    if daemon is None:
        daemon = TrainingDaemon(
            name=body.name,
            host=body.host,
            ip_address=ip,
            capabilities=body.capabilities,
        )
        session.add(daemon)
    else:
        await session.execute(
            update(TrainingDaemon)
            .where(TrainingDaemon.name == body.name)
            .values(
                host=body.host,
                ip_address=ip,
                capabilities=body.capabilities,
                last_seen=datetime.utcnow(),
            )
        )
        await session.refresh(daemon)

    await session.commit()
    await session.refresh(daemon)
    return daemon


@router.get("", response_model=list[DaemonOut])
async def list_daemons(session: SessionDep):
    result = await session.execute(
        select(TrainingDaemon).order_by(TrainingDaemon.last_seen.desc())
    )
    return result.scalars().all()
