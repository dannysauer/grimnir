"""
routers/history.py

GET /api/history/variance?receiver_id=1&minutes=60
    Per-minute amplitude variance from the csi_variance_1min continuous aggregate.
    Used by the 60-minute variance chart on the dashboard.

GET /api/history/snapshot?receiver_id=1&limit=1
    Raw amplitude/phase arrays for the N most recent samples.
    Used by the subcarrier amplitude heatmap.

GET /api/history/receivers
    All receivers with heartbeat data.
    Used by the dashboard on initial load.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..db import get_pool

router = APIRouter()


@router.get("/variance")
async def get_variance(
    receiver_id: int = Query(..., description="Receiver ID"),
    minutes: int = Query(60, ge=1, le=1440, description="Look-back window in minutes"),
):
    """Per-minute variance from the continuous aggregate."""
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT
            bucket,
            sample_count,
            avg_rssi,
            avg_amplitude_variance
        FROM csi_variance_1min
        WHERE receiver_id = $1
          AND bucket > NOW() - ($2 || ' minutes')::INTERVAL
        ORDER BY bucket ASC
        """,
        receiver_id,
        str(minutes),
    )
    return [
        {
            "time":               row["bucket"].isoformat(),
            "sample_count":       row["sample_count"],
            "avg_rssi":           round(float(row["avg_rssi"]), 2) if row["avg_rssi"] else None,
            "amplitude_variance": round(float(row["avg_amplitude_variance"]), 4)
                                  if row["avg_amplitude_variance"] else None,
        }
        for row in rows
    ]


@router.get("/snapshot")
async def get_snapshot(
    receiver_id: int = Query(..., description="Receiver ID"),
    limit: int = Query(1, ge=1, le=100, description="Number of recent samples"),
):
    """Raw amplitude/phase arrays — used to render the subcarrier heatmap."""
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT
            time, rssi,
            antenna_count, subcarrier_count,
            amplitude, phase, label
        FROM csi_samples
        WHERE receiver_id = $1
        ORDER BY time DESC
        LIMIT $2
        """,
        receiver_id,
        limit,
    )
    return [
        {
            "time":             row["time"].isoformat(),
            "rssi":             row["rssi"],
            "antenna_count":    row["antenna_count"],
            "subcarrier_count": row["subcarrier_count"],
            "amplitude":        list(row["amplitude"]),
            "phase":            list(row["phase"]),
            "label":            row["label"],
        }
        for row in rows
    ]


@router.get("/receivers")
async def get_receivers():
    """All receivers with heartbeat — used by the dashboard on load."""
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT
            r.id, r.name, r.mac, r.role, r.floor, r.location, r.active,
            h.last_seen,
            h.ip_address::text AS ip_address
        FROM receivers r
        LEFT JOIN receiver_heartbeats h ON h.receiver_id = r.id
        ORDER BY r.id
        """
    )
    return [dict(row) for row in rows]
