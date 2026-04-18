"""Shared-secret auth helpers for the ML control plane."""

from __future__ import annotations

import hmac
import os
from typing import Annotated

from fastapi import Header, HTTPException

ML_CONTROL_SHARED_SECRET = os.environ.get("ML_CONTROL_SHARED_SECRET", "")
ML_CONTROL_SECRET_HEADER = "X-Grimnir-ML-Control-Secret"


def require_ml_control_secret(
    provided_secret: Annotated[
        str | None,
        Header(alias=ML_CONTROL_SECRET_HEADER),
    ] = None,
) -> None:
    """Guard machine-only ML control endpoints when a shared secret is set."""
    if not ML_CONTROL_SHARED_SECRET:
        return
    if provided_secret is None or not hmac.compare_digest(
        provided_secret, ML_CONTROL_SHARED_SECRET
    ):
        raise HTTPException(
            status_code=401,
            detail=f"{ML_CONTROL_SECRET_HEADER} required",
        )
