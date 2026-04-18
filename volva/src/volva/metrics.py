"""Prometheus metrics for Völva (namespace ``volva_``)."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

predictions_served = Counter(
    "volva_predictions_served_total",
    "Predictions pushed to Freki /api/predictions/current",
)

prediction_errors = Counter(
    "volva_prediction_errors_total",
    "Failures during feature extraction, inference, or publish",
    ["stage"],  # "extract" | "predict" | "publish"
)

inference_duration_seconds = Histogram(
    "volva_inference_duration_seconds",
    "Wall-clock time for one feature-extract + predict cycle",
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0],
)

active_model_age_seconds = Gauge(
    "volva_active_model_age_seconds",
    "Age (wall-clock seconds) of the currently-loaded model",
)

active_model_id = Gauge(
    "volva_active_model_id",
    "ID of the currently-loaded model, or 0 if none",
)

csi_rows_consumed = Counter(
    "volva_csi_rows_consumed_total",
    "CSI rows received from Freki /api/csi-stream and fed into the window",
)
