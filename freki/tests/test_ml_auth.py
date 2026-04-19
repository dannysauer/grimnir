from __future__ import annotations

import pytest
from fastapi import HTTPException
from freki.routers import models

from freki import ml_auth


def test_model_upload_secret_is_noop_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "MODEL_UPLOAD_SHARED_SECRET", "")
    models.require_model_upload_secret(None)


def test_model_upload_secret_rejects_missing_or_wrong_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(models, "MODEL_UPLOAD_SHARED_SECRET", "expected-secret")

    with pytest.raises(HTTPException, match=models.MODEL_UPLOAD_SECRET_HEADER):
        models.require_model_upload_secret(None)

    with pytest.raises(HTTPException, match=models.MODEL_UPLOAD_SECRET_HEADER):
        models.require_model_upload_secret("wrong-secret")


def test_model_upload_secret_accepts_correct_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "MODEL_UPLOAD_SHARED_SECRET", "expected-secret")
    models.require_model_upload_secret("expected-secret")


def test_ml_control_secret_is_noop_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ml_auth, "ML_CONTROL_SHARED_SECRET", "")
    ml_auth.require_ml_control_secret(None)


def test_ml_control_secret_rejects_missing_or_wrong_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ml_auth, "ML_CONTROL_SHARED_SECRET", "expected-secret")

    with pytest.raises(HTTPException, match=ml_auth.ML_CONTROL_SECRET_HEADER):
        ml_auth.require_ml_control_secret(None)

    with pytest.raises(HTTPException, match=ml_auth.ML_CONTROL_SECRET_HEADER):
        ml_auth.require_ml_control_secret("wrong-secret")


def test_ml_control_secret_accepts_correct_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ml_auth, "ML_CONTROL_SHARED_SECRET", "expected-secret")
    ml_auth.require_ml_control_secret("expected-secret")
