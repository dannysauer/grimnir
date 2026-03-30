"""
routers/stream.py — Server-Sent Events endpoint

GET /api/stream

Streams a per-receiver CSI summary to the browser every second:
{
  "receivers": [
    {
      "id": 1, "name": "rx_ground",
      "avg_rssi": -65, "amplitude_variance": 12.4,
      "sample_count": 10, "last_seen": "2024-01-15T10:30:00Z",
      "floor": 0, "location": "Living room"
    }, ...
  ],
  "window_s": 5,
  "timestamp": "2024-01-15T10:30:01Z"
}
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..db import get_pool

router = APIRouter()

POLL_INTERVAL_S = 1.0   # how often to push to browser
WINDOW_S        = 5     # aggregate over last N seconds


async def _fetch_summary(pool) -> dict:
    """Pull the last WINDOW_S seconds of data, summarized per receiver."""
    rows = await pool.fetch(
        """
        SELECT
            r.id,
            r.name,
            r.floor,
            r.location,
            COUNT(s.time)                    AS sample_count,
            AVG(s.rssi)                      AS avg_rssi,
            MAX(s.time)                      AS last_seen,
            AVG(
                (SELECT VARIANCE(v) FROM UNNEST(s.amplitude) AS v)
            )                                AS amplitude_variance
        FROM receivers r
        LEFT JOIN csi_samples s
            ON s.receiver_id = r.id
            AND s.time > NOW() - ($1 || ' seconds')::INTERVAL
        WHERE r.role = 'receiver'
          AND r.active = true
        GROUP BY r.id, r.name, r.floor, r.location
        ORDER BY r.id
        """,
        str(WINDOW_S),
    )

    receivers = [
        {
            "id":                 row["id"],
            "name":               row["name"],
            "floor":              row["floor"],
            "location":           row["location"],
            "sample_count":       row["sample_count"],
            "avg_rssi":           round(float(row["avg_rssi"]), 1) if row["avg_rssi"] else None,
            "amplitude_variance": round(float(row["amplitude_variance"]), 4)
                                  if row["amplitude_variance"] else None,
            "last_seen":          row["last_seen"].isoformat() if row["last_seen"] else None,
        }
        for row in rows
    ]

    return {
        "receivers":  receivers,
        "window_s":   WINDOW_S,
        "timestamp":  datetime.now(tz=timezone.utc).isoformat(),
    }


async def _event_generator():
    pool = get_pool()
    try:
        while True:
            try:
                payload = await _fetch_summary(pool)
                yield f"data: {json.dumps(payload, default=str)}\n\n"
            except Exception as exc:
                yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"
            await asyncio.sleep(POLL_INTERVAL_S)
    except asyncio.CancelledError:
        pass


@router.get("/stream")
async def stream():
    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )
