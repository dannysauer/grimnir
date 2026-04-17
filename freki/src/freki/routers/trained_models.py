"""
routers/trained_models.py

POST /api/models              upload a trained model
GET  /api/models              list models (metadata only, no model_data bytes)
GET  /api/models/{id}         get model metadata
POST /api/models/{id}/activate  set as the active model
"""

from __future__ import annotations

from datetime import datetime

from csi_models import TrainedModel
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select, update

from ..db import SessionDep

router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class ModelCreate(BaseModel):
    name: str
    training_job_id: int | None = None
    metrics: dict = {}
    feature_config: dict = {}


class ModelOut(BaseModel):
    id: int
    name: str
    training_job_id: int | None
    is_active: bool
    metrics: dict
    feature_config: dict
    size_bytes: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("", response_model=ModelOut, status_code=201)
async def upload_model(
    file: UploadFile,
    name: str,
    session: SessionDep,
    training_job_id: int | None = None,
    metrics: str = "{}",
    feature_config: str = "{}",
):
    """Upload serialised model bytes (multipart/form-data)."""
    import json

    data = await file.read()
    model = TrainedModel(
        name=name,
        training_job_id=training_job_id,
        metrics=json.loads(metrics),
        feature_config=json.loads(feature_config),
        model_data=data,
        size_bytes=len(data),
    )
    session.add(model)
    await session.commit()
    await session.refresh(model)
    return model


@router.get("", response_model=list[ModelOut])
async def list_models(session: SessionDep):
    result = await session.execute(
        select(TrainedModel).order_by(TrainedModel.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{model_id}", response_model=ModelOut)
async def get_model_metadata(model_id: int, session: SessionDep):
    result = await session.execute(
        select(TrainedModel).where(TrainedModel.id == model_id)
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@router.get("/{model_id}/data")
async def download_model(model_id: int, session: SessionDep):
    """Download raw model bytes for deserialization by Völva."""
    result = await session.execute(
        select(TrainedModel).where(TrainedModel.id == model_id)
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return Response(
        content=model.model_data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="model_{model_id}.joblib"'},
    )


@router.post("/{model_id}/activate", response_model=ModelOut)
async def activate_model(model_id: int, session: SessionDep):
    """Set this model as active; clears is_active on all others atomically."""
    result = await session.execute(
        select(TrainedModel).where(TrainedModel.id == model_id)
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")

    await session.execute(
        update(TrainedModel).values(is_active=False)
    )
    await session.execute(
        update(TrainedModel).where(TrainedModel.id == model_id).values(is_active=True)
    )
    await session.commit()
    await session.refresh(model)
    return model
