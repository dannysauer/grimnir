"""
routers/models.py

GET  /api/models                 list trained models (no bytes)
GET  /api/models/active          return currently-active model metadata, or 404
GET  /api/models/{id}/data       stream the raw model_data bytes
POST /api/models                 upload a trained model (multipart/form-data).
                                When MODEL_UPLOAD_SHARED_SECRET is set,
                                requires X-Grimnir-Model-Upload-Secret.
POST /api/models/{id}/activate   make this the only active model
"""

from __future__ import annotations

import hmac
import json
import os
from datetime import datetime
from typing import Annotated, Any

from csi_models import TrainedModel
from csi_models.features import FeatureConfig
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import Select, func, select, text, update
from sqlalchemy.exc import DBAPIError

from ..db import SessionDep

router = APIRouter()

MODEL_UPLOAD_SHARED_SECRET = os.environ.get("MODEL_UPLOAD_SHARED_SECRET", "")
MODEL_UPLOAD_SECRET_HEADER = "X-Grimnir-Model-Upload-Secret"  # pragma: allowlist secret

# Advisory lock key that serializes model activation ("GRMMODEL" in ASCII).
MODEL_ACTIVATION_LOCK_ID = 0x47524D4D4F44454C
# Bounds on how long an activation waits, so a stuck lock can't pin
# connections from Freki's pool.
ACTIVATION_LOCK_TIMEOUT = "5s"
ACTIVATION_STATEMENT_TIMEOUT = "10s"


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


def _model_metadata() -> Select[Any]:
    """Select every ``ModelOut`` field without loading the model bytes."""
    return select(
        TrainedModel.id,
        TrainedModel.name,
        TrainedModel.training_job_id,
        TrainedModel.is_active,
        TrainedModel.metrics,
        TrainedModel.feature_config,
        func.octet_length(TrainedModel.model_data).label("size_bytes"),
        TrainedModel.created_at,
    )


def require_model_upload_secret(
    provided_secret: Annotated[
        str | None,
        Header(alias=MODEL_UPLOAD_SECRET_HEADER),
    ] = None,
) -> None:
    """Guard model uploads when a shared secret is configured."""
    if not MODEL_UPLOAD_SHARED_SECRET:
        return
    if provided_secret is None or not hmac.compare_digest(
        provided_secret, MODEL_UPLOAD_SHARED_SECRET
    ):
        raise HTTPException(
            status_code=401,
            detail=f"{MODEL_UPLOAD_SECRET_HEADER} required",
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=list[ModelOut])
async def list_models(session: SessionDep, limit: int = 50):
    limit = max(1, min(limit, 500))
    stmt = _model_metadata().order_by(TrainedModel.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return [ModelOut.model_validate(row._mapping) for row in result.all()]


@router.get("/active", response_model=ModelOut)
async def active_model(session: SessionDep):
    stmt = _model_metadata().where(TrainedModel.is_active.is_(True))
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
    _: None = Depends(require_model_upload_secret),
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
    result = await session.execute(_model_metadata().where(TrainedModel.id == model.id))
    return ModelOut.model_validate(result.one()._mapping)


@router.post("/{model_id}/activate", response_model=ModelOut)
async def activate_model(model_id: int, session: SessionDep):
    """Make one model active and every other model inactive.

    The partial unique index ``trained_models_one_active`` is checked row by
    row, so the old model has to be cleared before the new one is set. A
    transaction-scoped advisory lock serializes concurrent activations.

    This relies on READ COMMITTED, which the transaction sets explicitly:
    each statement after the lock wait takes a fresh snapshot, so the clearing
    UPDATE sees the row the previous lock holder made active. Under
    REPEATABLE READ the snapshot would predate the wait and miss it.
    """
    try:
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
        await session.execute(text(f"SET LOCAL lock_timeout = '{ACTIVATION_LOCK_TIMEOUT}'"))
        await session.execute(
            text(f"SET LOCAL statement_timeout = '{ACTIVATION_STATEMENT_TIMEOUT}'")
        )
        await session.execute(select(func.pg_advisory_xact_lock(MODEL_ACTIVATION_LOCK_ID)))
        target = await session.scalar(select(TrainedModel.id).where(TrainedModel.id == model_id))
        if target is None:
            await session.rollback()
            raise HTTPException(status_code=404, detail="Model not found")

        await session.execute(
            update(TrainedModel)
            .where(TrainedModel.is_active.is_(True), TrainedModel.id != model_id)
            .values(is_active=False)
        )
        await session.execute(
            update(TrainedModel).where(TrainedModel.id == model_id).values(is_active=True)
        )
        await session.commit()
    except DBAPIError:
        # A lock or statement timeout: nothing changed, and the caller can retry.
        await session.rollback()
        raise HTTPException(
            status_code=503, detail="Model activation timed out; try again"
        ) from None

    stmt = _model_metadata().where(TrainedModel.id == model_id)
    row = (await session.execute(stmt)).one()
    return ModelOut.model_validate(row._mapping)
