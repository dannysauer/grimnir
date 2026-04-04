"""
metrics.py — Prometheus metrics definitions for Freki.

Imported by routers that need to track custom metrics.
prometheus-fastapi-instrumentator auto-instruments HTTP request metrics;
this module adds application-level gauges.
"""

from __future__ import annotations

from prometheus_client import Gauge

sse_connections_active = Gauge(
    "freki_sse_connections_active",
    "Number of currently open SSE /api/stream connections",
)
