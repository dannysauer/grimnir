"""
routers/models.py

GET  /api/models                 list trained models (no bytes)
GET  /api/models/active          return currently-active model metadata, or 404
GET  /api/models/{id}/data       stream the raw model_data bytes
POST /api/models                 upload a trained model (multipart/form-data)
POST /api/models/{id}/activate   make this the active model (atomic swap)
"""

from __future__ import annotations

import json
from datetime import datetime

from csi_models import TrainedModel
from csi_models.features import FeatureConfig
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select, text

from ..db import SessionDep

router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class ModelOut(BaseModel):
    """Model metadata without the blob — used in list + detail responses."""

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


@router.get("", response_model=list[ModelOut])
async def list_models(session: SessionDep, limit: int = 50):
    limit = max(1, min(limit, 500))
    # Project octet_length(model_data) AS size_bytes to avoid loading the blob.
    stmt = (
        select(
            TrainedModel.id,
            TrainedModel.name,
            TrainedModel.training_job_id,
            TrainedModel.is_active,
            TrainedModel.metrics,
            TrainedModel.feature_config,
            text("octet_length(model_data) AS size_bytes"),
            TrainedModel.created_at,
        )
        .order_by(TrainedModel.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [ModelOut.model_validate(row._mapping) for row in result.all()]


@router.get("/active", response_model=ModelOut)
async def active_model(session: SessionDep):
    stmt = (
        select(
            TrainedModel.id,
            TrainedModel.name,
            TrainedModel.training_job_id,
            TrainedModel.is_active,
            TrainedModel.metrics,
            TrainedModel.feature_config,
            text("octet_length(model_data) AS size_bytes"),
            TrainedModel.created_at,
        )
        .where(TrainedModel.is_active.is_(True))
    )
    result = await session.execute(stmt)
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="No active model")
    return ModelOut.model_validate(row._mapping)


@router.get("/{model_id}/data")
async def model_data(model_id: int, session: SessionDep):
    result = await session.execute(
        select(TrainedModel.model_data).where(TrainedModel.id == model_id)
    )
    data = result.scalar_one_or_none()
    if data is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return Response(content=bytes(data), media_type="application/octet-stream")


@router.post("", response_model=ModelOut, status_code=201)
async def upload_model(
    session: SessionDep,
    name: str = Form(...),
    metrics: str = Form(...),
    feature_config: str = Form(...),
    training_job_id: int | None = Form(None),
    model_data: UploadFile = File(...),
):
    try:
        metrics_obj = json.loads(metrics)
        feature_config_obj = json.loads(feature_config)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid JSON: {exc}") from exc
    if not isinstance(metrics_obj, dict) or not isinstance(feature_config_obj, dict):
        raise HTTPException(status_code=422, detail="metrics and feature_config must be objects")

    try:
        FeatureConfig.model_validate(feature_config_obj)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid feature_config: {exc}") from exc

    raw = await model_data.read()
    if not raw:
        raise HTTPException(status_code=422, detail="model_data must not be empty")

    model = TrainedModel(
        name=name,
        training_job_id=training_job_id,
        metrics=metrics_obj,
        feature_config=feature_config_obj,
        model_data=raw,
    )
    session.add(model)
    await session.commit()
    await session.refresh(model)
    # Re-query to pick up size_bytes via octet_length projection.
    result = await session.execute(
        select(
            TrainedModel.id,
            TrainedModel.name,
            TrainedModel.training_job_id,
            TrainedModel.is_active,
            TrainedModel.metrics,
            TrainedModel.feature_config,
            text("octet_length(model_data) AS size_bytes"),
            TrainedModel.created_at,
        ).where(TrainedModel.id == model.id)
    )
    return ModelOut.model_validate(result.one()._mapping)


@router.post("/{model_id}/activate", response_model=ModelOut)
async def activate_model(model_id: int, session: SessionDep):
    # B5: single statement swaps the active model atomically so the partial
    # unique index on is_active = TRUE never sees two active rows.
    result = await session.execute(
        text(
            """
            WITH target AS (
                SELECT id FROM trained_models WHERE id = :target_id FOR UPDATE
            ),
            cleared AS (
                UPDATE trained_models
                   SET is_active = FALSE
                 WHERE is_active = TRUE AND id <> :target_id
            )
            UPDATE trained_models
               SET is_active = TRUE
             WHERE id = (SELECT id FROM target)
             RETURNING id
            """
        ),
        {"target_id": model_id},
    )
    activated = result.scalar_one_or_none()
    if activated is None:
        await session.rollback()
        raise HTTPException(status_code=404, detail="Model not found")
    await session.commit()

    # Return the activated model via the standard projection.
    stmt = (
        select(
            TrainedModel.id,
            TrainedModel.name,
            TrainedModel.training_job_id,
            TrainedModel.is_active,
            TrainedModel.metrics,
            TrainedModel.feature_config,
            text("octet_length(model_data) AS size_bytes"),
            TrainedModel.created_at,
        )
        .where(TrainedModel.id == model_id)
    )
    row = (await session.execute(stmt)).one()
    return ModelOut.model_validate(row._mapping)
