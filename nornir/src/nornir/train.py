"""
train.py — run one training job end-to-end.

Responsibilities:
  1. Stream labeled CSI rows from Freki's cursor-paginated
     ``/api/training-data`` endpoint (never buffers the full dataset — rows are
     windowed and discarded as they arrive).
  2. Window the stream per ``(receiver_id, label)`` contiguous run, extract one
     feature vector per window via ``csi_models.features.extract_features``.
  3. Fit ``sklearn.ensemble.RandomForestClassifier`` on (features → room name).
  4. Return the fitted model bytes + a small metrics dict suitable for the
     ``trained_models.metrics`` JSONB column.

The training target is the ``label`` column (room name). Per the plan's A2
carve-out, the count-of-occupants field on ``labels`` stays separate for v1;
Völva translates a predicted room into ``{room: {human_count: 1}}``.
"""

from __future__ import annotations

import io
import time
from collections.abc import AsyncIterator
from typing import Any

import joblib
import numpy as np
import structlog
from csi_models.features import FEATURE_VERSION, FeatureConfig, extract_features
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split

from .freki_client import FrekiClient
from .metrics import rows_fetched, training_duration_seconds

log = structlog.get_logger(__name__)

DEFAULT_WINDOW_SIZE = 50  # ~5 s of CSI at 10 Hz beacons
DEFAULT_HYPERPARAMS: dict[str, Any] = {
    "n_estimators": 100,
    "max_depth": 12,
    "random_state": 42,
    "n_jobs": -1,
}


# ── Windowing ─────────────────────────────────────────────────────────────────


async def _windows(
    row_stream: AsyncIterator[dict[str, Any]],
    *,
    window_size: int,
    feature_config: FeatureConfig,
) -> AsyncIterator[tuple[np.ndarray, str]]:
    """Yield ``(feature_vector, label)`` tuples.

    Rows arrive sorted by ``(time, receiver_id)``. To keep windows homogeneous
    we buffer a per-receiver backlog and flush it whenever the label changes
    or ``window_size`` rows have accumulated. A final partial buffer at stream
    end is discarded.
    """
    buffers: dict[int, list[dict[str, Any]]] = {}
    labels: dict[int, str] = {}

    async for row in row_stream:
        rid = row["receiver_id"]
        label = row["label"]
        buf = buffers.setdefault(rid, [])

        if rid in labels and labels[rid] != label:
            # Label transition — discard partial window; state resets.
            buf.clear()

        buf.append(row)
        labels[rid] = label

        if len(buf) >= window_size:
            yield extract_features(buf, feature_config), label
            buf.clear()


async def _collect_windows(
    row_stream: AsyncIterator[dict[str, Any]],
    *,
    window_size: int,
    feature_config: FeatureConfig,
) -> tuple[np.ndarray, np.ndarray, int]:
    features: list[np.ndarray] = []
    targets: list[str] = []
    row_count = 0

    async def counted() -> AsyncIterator[dict[str, Any]]:
        nonlocal row_count
        async for r in row_stream:
            row_count += 1
            yield r

    async for feat, label in _windows(
        counted(), window_size=window_size, feature_config=feature_config
    ):
        features.append(feat)
        targets.append(label)

    if not features:
        raise ValueError("no training windows produced — time window likely too short")
    widths = {f.shape[0] for f in features}
    if len(widths) > 1:
        raise ValueError(
            f"inconsistent feature widths across windows: {sorted(widths)} "
            "(did antenna/subcarrier count change mid-run?)"
        )
    return np.vstack(features).astype(np.float32), np.asarray(targets), row_count


# ── Model fit / serialisation ─────────────────────────────────────────────────


def _fit_model(
    x: np.ndarray, y: np.ndarray, hyperparams: dict[str, Any]
) -> tuple[RandomForestClassifier, dict[str, Any]]:
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.2, random_state=hyperparams.get("random_state", 42), stratify=y
    )
    clf = RandomForestClassifier(**hyperparams)
    fit_start = time.perf_counter()
    clf.fit(x_train, y_train)
    fit_duration = time.perf_counter() - fit_start
    training_duration_seconds.observe(fit_duration)

    y_pred = clf.predict(x_test)
    metrics = {
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "f1_macro": float(f1_score(y_test, y_pred, average="macro")),
        "n_train_windows": int(len(x_train)),
        "n_test_windows": int(len(x_test)),
        "feature_dim": int(x.shape[1]),
        "fit_duration_s": round(fit_duration, 3),
        "classes": sorted(clf.classes_.tolist()),
    }
    return clf, metrics


def _serialize(clf: RandomForestClassifier) -> bytes:
    buf = io.BytesIO()
    joblib.dump(clf, buf, compress=3)
    return buf.getvalue()


# ── Entry point ───────────────────────────────────────────────────────────────


async def run_job(
    *,
    client: FrekiClient,
    job: dict[str, Any],
) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    """Train one job end-to-end.

    Returns ``(model_bytes, metrics, feature_config_dict)``. Raises on any
    failure — the caller (main.py) reports to Freki.
    """
    spec = job["spec"]
    feature_config = FeatureConfig.model_validate(spec.get("feature_config") or {})
    window_size = int(spec.get("hyperparams", {}).get("window_size", DEFAULT_WINDOW_SIZE))
    hyperparams = {**DEFAULT_HYPERPARAMS, **spec.get("hyperparams", {})}
    # window_size is a windowing knob, not an sklearn parameter.
    hyperparams.pop("window_size", None)

    log.info(
        "train.started",
        job_id=job["id"],
        rooms=spec["rooms"],
        window_size=window_size,
        feature_version=feature_config.version,
    )

    row_stream = client.iter_training_data(
        time_start=spec["time_start"],
        time_end=spec["time_end"],
        rooms=spec["rooms"],
    )
    x, y, row_count = await _collect_windows(
        row_stream, window_size=window_size, feature_config=feature_config
    )
    rows_fetched.observe(row_count)

    log.info(
        "train.dataset_built",
        job_id=job["id"],
        rows=row_count,
        windows=int(len(y)),
        classes=sorted(set(y.tolist())),
    )

    clf, metrics = _fit_model(x, y, hyperparams)
    metrics["n_rows_fetched"] = row_count
    metrics["window_size"] = window_size
    metrics["feature_version"] = FEATURE_VERSION

    model_bytes = _serialize(clf)
    log.info(
        "train.finished",
        job_id=job["id"],
        accuracy=metrics["accuracy"],
        f1_macro=metrics["f1_macro"],
        model_bytes=len(model_bytes),
    )

    return model_bytes, metrics, feature_config.model_dump(mode="json")
