"""
metrics.py — Prometheus metrics definitions for Geri.

Imported by both main.py and db.py to avoid circular imports.
All metrics use the "geri_" namespace.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

packets_received = Counter(
    "geri_packets_received_total",
    "UDP CSI packets successfully parsed and queued",
    ["receiver_name"],
)

packets_invalid = Counter(
    "geri_packets_invalid_total",
    "UDP packets that failed parsing (bad magic, truncated, etc.)",
)

packets_dropped = Counter(
    "geri_packets_dropped_total",
    "UDP packets dropped because the internal queue was full",
)

batch_writes = Counter(
    "geri_batch_writes_total",
    "DB batch write operations",
    ["status"],  # "success" | "error"
)

batch_write_duration = Histogram(
    "geri_batch_write_duration_seconds",
    "Wall-clock time to flush one batch to TimescaleDB",
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0],
)

batch_size = Histogram(
    "geri_batch_size_rows",
    "Number of CSI rows in each batch write",
    buckets=[1, 5, 10, 25, 50, 100, 200, 500],
)

receiver_last_seen = Gauge(
    "geri_receiver_last_seen_timestamp_seconds",
    "Unix timestamp of the last heartbeat received from this Muninn device",
    ["receiver_name"],
)
