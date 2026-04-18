"""
routers/training_jobs.py

POST   /api/training-jobs                enqueue a new training job
GET    /api/training-jobs                list jobs (optional status filter)
POST   /api/training-jobs/{id}/claim     daemon claims a queued job
POST   /api/training-jobs/{id}/heartbeat daemon reports progress (orphan-reaper signal)
POST   /api/training-jobs/{id}/complete  job finished successfully
POST   /api/training-jobs/{id}/fail      job errored
POST   /api/training-jobs/{id}/cancel    cancel queued/running job

Lifecycle: queued → running → complete / failed / cancelled.

The claim endpoint uses a conditional UPDATE … WHERE status='queued' RETURNING
so two daemons racing on the same job cannot both succeed (see review B6).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from csi_models import Room, TrainingJob
from csi_models.features import FeatureConfig
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from ..db import SessionDep

router = APIRouter()

JobStatus = Literal["queued", "running", "failed", "complete", "cancelled"]


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class JobSpec(BaseModel):
    """Payload passed to the training daemon.

    `occupants` from labels is used as the human-count target (pets are
    currently lumped together in that field; see issue #14).
    """

    model_type: str = Field(default="random_forest")
    hyperparams: dict[str, Any] = Field(default_factory=dict)
    feature_config: FeatureConfig = Field(default_factory=FeatureConfig)
    time_start: datetime
    time_end: datetime
    rooms: list[str] = Field(min_length=1, max_length=32)


class JobCreate(BaseModel):
    spec: JobSpec


class JobOut(BaseModel):
    id: int
    status: JobStatus
    spec: dict
    daemon_id: int | None
    created_at: datetime
    claimed_at: datetime | None
    heartbeat_at: datetime | None
    completed_at: datetime | None
    error: str | None

    model_config = {"from_attributes": True}


class ClaimBody(BaseModel):
    daemon_id: int


class FailBody(BaseModel):
    error: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("", response_model=JobOut, status_code=201)
async def create_job(body: JobCreate, session: SessionDep):
    if body.spec.time_end <= body.spec.time_start:
        raise HTTPException(status_code=422, detail="time_end must be after time_start")

    # A1: validate every room name exists.
    known = await session.execute(select(Room.name).where(Room.name.in_(body.spec.rooms)))
    known_names = {row[0] for row in known.all()}
    unknown = [r for r in body.spec.rooms if r not in known_names]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown room(s): {', '.join(sorted(unknown))}",
        )

    job = TrainingJob(spec=body.spec.model_dump(mode="json"))
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


@router.get("", response_model=list[JobOut])
async def list_jobs(session: SessionDep, status: JobStatus | None = None, limit: int = 50):
    limit = max(1, min(limit, 500))
    stmt = select(TrainingJob).order_by(TrainingJob.created_at.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(TrainingJob.status == status)
    result = await session.execute(stmt)
    return result.scalars().all()


@router.post("/{job_id}/claim", response_model=JobOut)
async def claim_job(job_id: int, body: ClaimBody, session: SessionDep):
    # B6: single conditional UPDATE — empty result means someone else won.
    stmt = (
        update(TrainingJob)
        .where(TrainingJob.id == job_id, TrainingJob.status == "queued")
        .values(
            status="running",
            daemon_id=body.daemon_id,
            claimed_at=func.now(),
            heartbeat_at=func.now(),
        )
        .returning(TrainingJob)
    )
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        # Either the job doesn't exist or it's already claimed.
        await session.rollback()
        raise HTTPException(status_code=409, detail="Job not available for claim")
    await session.commit()
    return job


@router.post("/{job_id}/heartbeat", response_model=JobOut)
async def heartbeat_job(job_id: int, session: SessionDep):
    stmt = (
        update(TrainingJob)
        .where(TrainingJob.id == job_id, TrainingJob.status == "running")
        .values(heartbeat_at=func.now())
        .returning(TrainingJob)
    )
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Job is not running")
    await session.commit()
    return job


@router.post("/{job_id}/complete", response_model=JobOut)
async def complete_job(job_id: int, session: SessionDep):
    stmt = (
        update(TrainingJob)
        .where(TrainingJob.id == job_id, TrainingJob.status == "running")
        .values(status="complete", completed_at=func.now())
        .returning(TrainingJob)
    )
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Job is not running")
    await session.commit()
    return job


@router.post("/{job_id}/fail", response_model=JobOut)
async def fail_job(job_id: int, body: FailBody, session: SessionDep):
    stmt = (
        update(TrainingJob)
        .where(TrainingJob.id == job_id, TrainingJob.status == "running")
        .values(status="failed", completed_at=func.now(), error=body.error)
        .returning(TrainingJob)
    )
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Job is not running")
    await session.commit()
    return job


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(job_id: int, session: SessionDep):
    stmt = (
        update(TrainingJob)
        .where(
            TrainingJob.id == job_id,
            TrainingJob.status.in_(["queued", "running"]),
        )
        .values(status="cancelled", completed_at=func.now())
        .returning(TrainingJob)
    )
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Job is not queued or running")
    await session.commit()
    return job
