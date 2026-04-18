"""Shared CSI feature extraction used by both Nornir (training) and Völva (inference).

Both services compute features identically from the same underlying CSI rows;
any drift between them silently produces bad predictions. This module is the
single source of truth.

Requires the ``features`` optional extra on ``csi-models``:

    pip install 'csi-models[features]'

Geri does not need these extras.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field, field_validator, model_validator

# Bump when extract_features() output changes in a way that breaks models
# trained on the old version. Völva compares the running version against the
# model's ``feature_config.version`` and refuses to load incompatible models.
FEATURE_VERSION = 1

Stat = Literal["mean", "var"]


class FeatureConfig(BaseModel):
    """Configuration for per-window CSI feature extraction.

    Stored alongside each trained model so Völva can validate compatibility
    at load time.
    """

    version: int = Field(default=FEATURE_VERSION, ge=1)
    stats: list[Stat] = Field(default_factory=lambda: ["mean", "var"], min_length=1)
    include_amplitude: bool = True
    include_phase: bool = False  # hardware offsets contaminate phase; see issue #7

    @field_validator("stats")
    @classmethod
    def _stats_unique(cls, v: list[Stat]) -> list[Stat]:
        if len(set(v)) != len(v):
            raise ValueError("stats entries must be unique")
        return v

    @model_validator(mode="after")
    def _at_least_one_channel(self) -> FeatureConfig:
        if not (self.include_amplitude or self.include_phase):
            raise ValueError("at least one of include_amplitude/include_phase must be True")
        return self


def _stack(rows: Sequence[dict[str, Any]], key: Literal["amplitude", "phase"]) -> np.ndarray:
    return np.asarray([r[key] for r in rows], dtype=np.float32)


def _apply_stats(stack: np.ndarray, stats: Sequence[Stat]) -> np.ndarray:
    parts: list[np.ndarray] = []
    for stat in stats:
        if stat == "mean":
            parts.append(stack.mean(axis=0))
        elif stat == "var":
            parts.append(stack.var(axis=0))
        else:  # pragma: no cover — guarded by FeatureConfig validation
            raise ValueError(f"unsupported stat: {stat}")
    return np.concatenate(parts, axis=0).astype(np.float32)


def extract_features(
    rows: Iterable[dict[str, Any]],
    config: FeatureConfig,
) -> np.ndarray:
    """Extract a 1-D feature vector from CSI rows that cover one window.

    Each row must carry ``amplitude`` and ``phase`` as flat lists/arrays of
    length ``antenna_count * subcarrier_count``. All rows in the window must
    share the same shape; callers are responsible for windowing and shape
    consistency.

    Returns a float32 vector whose length is
    ``len(stats) * n_values * (include_amplitude + include_phase)``.

    Raises ValueError if ``rows`` is empty or amplitude/phase widths disagree.
    """
    rows_seq: list[dict[str, Any]] = list(rows)
    if not rows_seq:
        raise ValueError("extract_features requires at least one row")

    parts: list[np.ndarray] = []
    width: int | None = None

    if config.include_amplitude:
        amp = _stack(rows_seq, "amplitude")
        width = amp.shape[1]
        parts.append(_apply_stats(amp, config.stats))

    if config.include_phase:
        phase = _stack(rows_seq, "phase")
        if width is not None and phase.shape[1] != width:
            raise ValueError("amplitude and phase row widths disagree")
        parts.append(_apply_stats(phase, config.stats))

    return np.concatenate(parts, axis=0).astype(np.float32)
