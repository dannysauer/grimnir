"""state.py — Module-level active model and latest predictions."""

from __future__ import annotations

from typing import Any

# Active model: (model_id, sklearn_estimator) or (None, None) if not loaded
active_model_id: int | None = None
active_model: Any = None  # sklearn estimator

# Latest predictions pushed to Freki
latest_predictions: dict[str, Any] = {}
