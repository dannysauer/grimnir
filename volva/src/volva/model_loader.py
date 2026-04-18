"""
model_loader.py — fetch and load the currently-active model from Freki.

The loader lives behind a single `ActiveModel` dataclass the rest of the
service consumes. A background task periodically re-queries
``/api/models/active`` and swaps the in-memory model atomically when the
active id changes. Feature-version mismatches are refused at load time
(see plan A11).
"""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import joblib
import structlog
from csi_models.features import FEATURE_VERSION, FeatureConfig

log = structlog.get_logger(__name__)


class ModelLoadError(RuntimeError):
    pass


@dataclass
class ActiveModel:
    id: int
    name: str
    classifier: Any  # sklearn RandomForestClassifier
    feature_config: FeatureConfig
    classes: list[str]
    created_at: datetime


async def fetch_active(client: httpx.AsyncClient) -> ActiveModel | None:
    """Return the freshly-loaded active model, or None if Freki has none."""
    meta_resp = await client.get("/api/models/active")
    if meta_resp.status_code == 404:
        return None
    meta_resp.raise_for_status()
    meta = meta_resp.json()

    fc = FeatureConfig.model_validate(meta["feature_config"])
    if fc.version != FEATURE_VERSION:
        raise ModelLoadError(
            f"model {meta['id']} feature_config.version={fc.version} "
            f"but this Völva build is at {FEATURE_VERSION}"
        )

    data_resp = await client.get(f"/api/models/{meta['id']}/data")
    data_resp.raise_for_status()
    clf = joblib.load(io.BytesIO(data_resp.content))

    if not hasattr(clf, "predict") or not hasattr(clf, "classes_"):
        raise ModelLoadError("loaded object is not a sklearn classifier")

    return ActiveModel(
        id=meta["id"],
        name=meta["name"],
        classifier=clf,
        feature_config=fc,
        classes=sorted(clf.classes_.tolist()),
        created_at=datetime.fromisoformat(meta["created_at"]),
    )


async def refresh_loop(
    client: httpx.AsyncClient,
    holder: ModelHolder,
    interval_s: float,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        try:
            latest = await fetch_active(client)
        except httpx.HTTPError as exc:
            log.warning("model.refresh_fetch_failed", error=str(exc))
        except ModelLoadError as exc:
            log.warning("model.refresh_load_failed", error=str(exc))
        else:
            if latest is None:
                if holder.current is not None:
                    log.info("model.unloaded")
                    holder.set(None)
            elif holder.current is None or holder.current.id != latest.id:
                log.info("model.loaded", model_id=latest.id, classes=latest.classes)
                holder.set(latest)

        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
            return
        except TimeoutError:
            continue


class ModelHolder:
    """Atomic holder for the currently-active model."""

    def __init__(self) -> None:
        self._model: ActiveModel | None = None

    @property
    def current(self) -> ActiveModel | None:
        return self._model

    def set(self, model: ActiveModel | None) -> None:
        # Simple atomic swap — reads via `current` see either old or new.
        self._model = model

    def age_seconds(self) -> float:
        if self._model is None:
            return 0.0
        return (datetime.now(tz=UTC) - self._model.created_at).total_seconds()
