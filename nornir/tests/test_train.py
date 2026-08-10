from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from csi_models.features import FEATURE_VERSION

from nornir import train


class _FakeClient:
    """Stand-in for FrekiClient; iter_training_data is never consumed here
    because _collect_windows is stubbed to return a fixed dataset."""

    def iter_training_data(self, **_kwargs: Any):
        async def _empty():
            if False:
                yield {}

        return _empty()


@pytest.mark.asyncio
async def test_run_job_trains_and_serializes_via_offloaded_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A tiny, linearly separable two-class set; enough per class for the
    # stratified 80/20 split inside _fit_model.
    x = np.array([[float(i), float(i)] for i in range(10)], dtype=np.float32)
    y = np.array(["kitchen", "garage"] * 5)

    async def _fake_collect(row_stream, *, window_size, feature_config):
        return x, y, 200

    monkeypatch.setattr(train, "_collect_windows", _fake_collect)

    job = {
        "id": 1,
        "spec": {
            "rooms": ["kitchen", "garage"],
            "time_start": "2026-06-01T00:00:00Z",
            "time_end": "2026-06-01T01:00:00Z",
            "feature_config": {"version": FEATURE_VERSION},
            "hyperparams": {"n_estimators": 5, "window_size": 50},
        },
    }

    model_bytes, metrics, feature_config = await train.run_job(client=_FakeClient(), job=job)

    assert isinstance(model_bytes, bytes) and model_bytes
    assert metrics["window_size"] == 50
    assert metrics["feature_version"] == FEATURE_VERSION
    assert metrics["n_rows_fetched"] == 200
    assert sorted(metrics["classes"]) == ["garage", "kitchen"]
    assert feature_config["version"] == FEATURE_VERSION
