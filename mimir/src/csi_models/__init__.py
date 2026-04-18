"""Shared Grimnir database models and bootstrap helpers."""

from __future__ import annotations

from .engine import get_engine, get_session_factory, init_engine
from .migrate import run_migrations
from .models import (
    Base,
    CsiSample,
    CurrentPrediction,
    Label,
    Receiver,
    ReceiverHeartbeat,
    Room,
    TrainedModel,
    TrainingDaemon,
    TrainingJob,
    TrainingSample,
)

# ``csi_models.features`` is intentionally not re-exported here: it depends on
# numpy/pydantic, which Geri does not need. Consumers that use feature
# extraction (Nornir, Völva, Freki) install ``csi-models[features]`` and
# import from ``csi_models.features`` directly.

__all__ = [
    "Base",
    "CsiSample",
    "CurrentPrediction",
    "Label",
    "Receiver",
    "ReceiverHeartbeat",
    "Room",
    "TrainedModel",
    "TrainingDaemon",
    "TrainingJob",
    "TrainingSample",
    "get_engine",
    "get_session_factory",
    "init_engine",
    "run_migrations",
]
