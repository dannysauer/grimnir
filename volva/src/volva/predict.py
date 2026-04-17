"""predict.py — Feature extraction and model inference.

Feature pipeline version must match nornir/src/nornir/train.py.
The feature_config stored with the model is validated on load.
"""

from __future__ import annotations

from typing import Any

import numpy as np

# Must match FEATURE_CONFIG_VERSION in nornir/train.py
SUPPORTED_FEATURE_VERSION = "v1"


def validate_feature_config(feature_config: dict) -> None:
    """Raise ValueError if the model's feature_config is incompatible."""
    version = feature_config.get("version")
    if version != SUPPORTED_FEATURE_VERSION:
        raise ValueError(
            f"Model feature_config version '{version}' is not supported "
            f"(expected '{SUPPORTED_FEATURE_VERSION}')"
        )


def extract_features(sample: dict[str, Any]) -> np.ndarray:
    """Compute per-subcarrier mean and variance from amplitude array.

    Must produce the same shape as nornir/train.py _extract_features().
    """
    n_ant = sample["antenna_count"]
    n_sub = sample["subcarrier_count"]
    amp = np.array(sample["amplitude"], dtype=np.float32).reshape(n_ant, n_sub)
    means = amp.mean(axis=0)
    variances = amp.var(axis=0)
    return np.concatenate([means, variances])


def predict_room_occupancy(
    model: Any,
    snapshot: dict[str, Any],
) -> dict[str, dict[str, int]]:
    """Apply model to a Freki SSE snapshot and return per-room human counts.

    snapshot is the JSON payload from GET /api/stream, which contains a list
    of receiver readings. We aggregate features across all receivers and
    predict occupancy per room using the model.

    Returns: {"room_name": {"human_count": N}, ...}
    """
    receivers = snapshot.get("receivers", [])
    if not receivers:
        return {}

    feature_vectors = []
    for recv in receivers:
        if recv.get("amplitude") and recv.get("subcarrier_count"):
            try:
                features = extract_features(recv)
                feature_vectors.append(features)
            except Exception:
                continue

    if not feature_vectors:
        return {}

    # Average features across receivers for a combined representation
    X = np.stack(feature_vectors).mean(axis=0, keepdims=True)

    try:
        count = int(model.predict(X)[0])
    except Exception:
        return {}

    # Until multi-room models are trained, report the prediction against all
    # rooms the model was trained on. The label in the snapshot tells us the
    # current room context if available.
    rooms: list[str] = snapshot.get("rooms", [])
    if not rooms:
        rooms = ["unknown"]

    return {room: {"human_count": count} for room in rooms}
