"""
routers/training_jobs.py

POST   /api/training-jobs               create a queued job
GET    /api/training-jobs               list jobs (optional ?status= filter)
POST   /api/training-jobs/{id}/claim    daemon claims a queued job
POST   /api/training-jobs/{id}/heartbeat  daemon heartbeat during training
POST   /api/training-jobs/{id}/complete   mark job complete
POST   /api/training-jobs/{id}/fail       mark job failed
POST   /api/training-jobs/{id}/cancel     cancel a queued or running job
"""

from __future__ import annotations

from datetime import UTC, datetime

from csi_models import TrainingDaemon, TrainingJob
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, update

from ..db import SessionDep

router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class JobCreate(BaseModel):
    spec: dict


class JobOut(BaseModel):
    id: int
    status: str
    spec: dict
    daemon_id: int | None
    created_at: datetime
    claimed_at: datetime | None
    heartbeat_at: datetime | None
    completed_at: datetime | None
    error: str | None

    model_config = {"from_attributes": True}


class ClaimRequest(BaseModel):
    daemon_name: str


class FailRequest(BaseModel):
    error: str


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _get_job_or_404(job_id: int, session: SessionDep) -> TrainingJob:
    result = await session.execute(
        select(TrainingJob).where(TrainingJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("", response_model=JobOut, status_code=201)
async def create_job(body: JobCreate, session: SessionDep):
    job = TrainingJob(spec=body.spec)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


@router.get("", response_model=list[JobOut])
async def list_jobs(
    session: SessionDep,
    status: str | None = Query(default=None),
):
    stmt = select(TrainingJob).order_by(TrainingJob.created_at.desc())
    if status is not None:
        stmt = stmt.where(TrainingJob.status == status)
    result = await session.execute(stmt)
    return result.scalars().all()


@router.post("/{job_id}/claim", response_model=JobOut)
async def claim_job(job_id: int, body: ClaimRequest, session: SessionDep):
    job = await _get_job_or_404(job_id, session)
    if job.status != "queued":
        raise HTTPException(
            status_code=409, detail=f"Job is not queued (current status: {job.status})"
        )

    daemon_result = await session.execute(
        select(TrainingDaemon).where(TrainingDaemon.name == body.daemon_name)
    )
    daemon = daemon_result.scalar_one_or_none()
    if daemon is None:
        raise HTTPException(status_code=404, detail="Daemon not found — send a heartbeat first")

    now = datetime.now(tz=UTC)
    await session.execute(
        update(TrainingJob)
        .where(TrainingJob.id == job_id)
        .values(status="running", daemon_id=daemon.id, claimed_at=now, heartbeat_at=now)
    )
    await session.commit()
    await session.refresh(job)
    return job


@router.post("/{job_id}/heartbeat", response_model=JobOut)
async def job_heartbeat(job_id: int, session: SessionDep):
    job = await _get_job_or_404(job_id, session)
    if job.status != "running":
        raise HTTPException(
            status_code=409, detail=f"Job is not running (current status: {job.status})"
        )
    await session.execute(
        update(TrainingJob)
        .where(TrainingJob.id == job_id)
        .values(heartbeat_at=datetime.now(tz=UTC))
    )
    await session.commit()
    await session.refresh(job)
    return job


@router.post("/{job_id}/complete", response_model=JobOut)
async def complete_job(job_id: int, session: SessionDep):
    job = await _get_job_or_404(job_id, session)
    if job.status != "running":
        raise HTTPException(
            status_code=409, detail=f"Job is not running (current status: {job.status})"
        )
    await session.execute(
        update(TrainingJob)
        .where(TrainingJob.id == job_id)
        .values(status="complete", completed_at=datetime.now(tz=UTC))
    )
    await session.commit()
    await session.refresh(job)
    return job


@router.post("/{job_id}/fail", response_model=JobOut)
async def fail_job(job_id: int, body: FailRequest, session: SessionDep):
    job = await _get_job_or_404(job_id, session)
    if job.status not in ("running", "queued"):
        raise HTTPException(
            status_code=409,
            detail=f"Job cannot be failed from status: {job.status}",
        )
    await session.execute(
        update(TrainingJob)
        .where(TrainingJob.id == job_id)
        .values(status="failed", error=body.error, completed_at=datetime.now(tz=UTC))
    )
    await session.commit()
    await session.refresh(job)
    return job


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(job_id: int, session: SessionDep):
    job = await _get_job_or_404(job_id, session)
    if job.status not in ("queued", "running"):
        raise HTTPException(
            status_code=409,
            detail=f"Job cannot be cancelled from status: {job.status}",
        )
    await session.execute(
        update(TrainingJob)
        .where(TrainingJob.id == job_id)
        .values(status="cancelled", completed_at=datetime.now(tz=UTC))
    )
    await session.commit()
    await session.refresh(job)
    return job
