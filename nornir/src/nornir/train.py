"""train.py — Feature extraction and sklearn model training."""

from __future__ import annotations

import asyncio
import io
from collections.abc import AsyncGenerator
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix
from sklearn.model_selection import train_test_split

from .client import FrekiClient

# Feature config version — must match predict.py in Völva.
FEATURE_CONFIG_VERSION = "v1"


def _extract_features(sample: dict[str, Any]) -> np.ndarray:
    """Compute per-subcarrier mean and variance from amplitude array."""
    n_ant = sample["antenna_count"]
    n_sub = sample["subcarrier_count"]
    amp = np.array(sample["amplitude"], dtype=np.float32).reshape(n_ant, n_sub)
    means = amp.mean(axis=0)
    variances = amp.var(axis=0)
    return np.concatenate([means, variances])


async def train_model(
    client: FrekiClient,
    job_id: int,
    spec: dict[str, Any],
) -> tuple[bytes, dict, dict]:
    """
    Stream training data, fit a RandomForest, return (model_bytes, metrics, feature_config).
    """
    time_start: str = spec["time_start"]
    time_end: str = spec["time_end"]
    rooms: list[str] | None = spec.get("rooms")
    hyperparams: dict = spec.get("hyperparams", {})
    n_estimators: int = int(hyperparams.get("n_estimators", 100))
    max_depth: int | None = hyperparams.get("max_depth")

    X_list: list[np.ndarray] = []
    y_list: list[int] = []

    async for sample in client.stream_training_data(time_start, time_end, rooms):
        features = _extract_features(sample)
        # label is the room name; use human count from label table join if available,
        # otherwise default 1-present encoding (label non-null = 1 occupant)
        occupants = sample.get("occupants", 1)
        X_list.append(features)
        y_list.append(int(occupants))

    if not X_list:
        raise ValueError("No labeled samples found for the given spec")

    X = np.stack(X_list)
    y = np.array(y_list)

    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y if len(np.unique(y)) > 1 else None
    )

    def _fit() -> tuple[RandomForestClassifier, float, list, list]:
        clf = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            n_jobs=-1,
            random_state=42,
        )
        clf.fit(X_train, y_train)
        y_pred = clf.predict(X_val)
        acc = float(accuracy_score(y_val, y_pred))
        cm = confusion_matrix(y_val, y_pred).tolist()
        classes = sorted(np.unique(y).tolist())
        return clf, acc, cm, classes

    # sklearn fitting is CPU-bound — run in a thread to keep the event loop free
    clf, acc, cm, classes = await asyncio.to_thread(_fit)

    metrics = {
        "accuracy": acc,
        "confusion_matrix": cm,
        "confusion_matrix_labels": classes,
        "n_samples": len(X),
        "n_train": len(X_train),
        "n_val": len(X_val),
        "train_start": time_start,
        "train_end": time_end,
        "rooms": rooms,
    }

    feature_config = {
        "version": FEATURE_CONFIG_VERSION,
        "stat_fns": ["mean", "var"],
        "use_phase": False,
        "n_features": X.shape[1],
    }

    buf = io.BytesIO()
    joblib.dump(clf, buf)
    model_bytes = buf.getvalue()

    return model_bytes, metrics, feature_config
