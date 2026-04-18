"""
metrics.py — Prometheus metrics for Nornir.

All metrics use the ``nornir_`` namespace. Exposed on ``METRICS_PORT`` (default
8001), mirroring Geri's secondary-port convention.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

jobs_claimed = Counter(
    "nornir_jobs_claimed_total",
    "Training jobs successfully claimed by this daemon",
)

jobs_completed = Counter(
    "nornir_jobs_completed_total",
    "Training jobs that finished and uploaded a model",
)

jobs_failed = Counter(
    "nornir_jobs_failed_total",
    "Training jobs that raised an error during training or upload",
    ["stage"],  # "fetch" | "train" | "upload" | "report"
)

training_duration_seconds = Histogram(
    "nornir_training_duration_seconds",
    "Wall-clock time to train one model (fit only, excludes fetch/upload)",
    buckets=[1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600],
)

rows_fetched = Histogram(
    "nornir_rows_fetched_per_job",
    "Number of training sample rows pulled from /api/training-data per job",
    buckets=[100, 1_000, 10_000, 100_000, 1_000_000, 10_000_000],
)

queue_depth = Gauge(
    "nornir_queue_depth",
    "Training jobs currently in 'queued' state (polled from Freki)",
)
