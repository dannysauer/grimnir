"""
predict.py — live inference loop.

Subscribes to Freki's ``/api/csi-stream`` (the raw-CSI SSE introduced for B1),
maintains a sliding per-receiver window, and whenever a receiver's buffer
reaches ``WINDOW_SIZE`` rows it:

  1. Extracts features via ``csi_models.features.extract_features`` (same
     function Nornir trained with — see plan B4).
  2. Predicts the current room with the active classifier.
  3. Aggregates per-receiver predictions with simple majority vote across a
     recent history per receiver.
  4. Publishes ``PUT /api/predictions/current`` with the
     ``{timestamp, model_id, rooms}`` envelope (issue #19 shape).

Windowing is non-overlapping for v1; tuning overlap/stride is a follow-up.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import Counter, deque
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from csi_models.features import extract_features
from httpx_sse import aconnect_sse

from .metrics import (
    csi_rows_consumed,
    inference_duration_seconds,
    prediction_errors,
    predictions_served,
)
from .model_loader import ActiveModel, ModelHolder

log = structlog.get_logger(__name__)

DEFAULT_WINDOW_SIZE = 50
VOTE_HISTORY = 5  # last N per-receiver predictions to majority-vote across


class _ReceiverState:
    __slots__ = ("buf", "votes")

    def __init__(self) -> None:
        self.buf: list[dict[str, Any]] = []
        self.votes: deque[str] = deque(maxlen=VOTE_HISTORY)


def _predict_once(
    model: ActiveModel,
    buf: list[dict[str, Any]],
) -> str:
    features = extract_features(buf, model.feature_config)
    return str(model.classifier.predict(features.reshape(1, -1))[0])


def _aggregate(
    votes_by_receiver: dict[int, deque[str]],
    known_rooms: list[str],
) -> dict[str, dict[str, int]]:
    """Majority-vote across receivers → human_count per room.

    A room gets human_count=1 if any receiver's most-recent vote picked it
    (ties broken arbitrarily by Counter ordering). Empty vote history → all
    rooms 0 (no-op publish).
    """
    winners: set[str] = set()
    for votes in votes_by_receiver.values():
        if not votes:
            continue
        counts = Counter(votes)
        top, _ = counts.most_common(1)[0]
        winners.add(top)
    return {room: {"human_count": 1 if room in winners else 0} for room in known_rooms}


async def _maybe_publish(
    client: httpx.AsyncClient,
    model: ActiveModel,
    votes_by_receiver: dict[int, deque[str]],
    last_published: dict[str, Any] | None,
) -> dict[str, Any] | None:
    rooms = _aggregate(votes_by_receiver, model.classes)
    if (
        last_published is not None
        and model.id == last_published.get("model_id")
        and rooms == last_published.get("rooms")
    ):
        return last_published  # unchanged, skip re-publish

    payload = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "model_id": model.id,
        "rooms": rooms,
    }
    try:
        response = await client.put("/api/predictions/current", json=payload)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        prediction_errors.labels(stage="publish").inc()
        log.warning("predict.publish_failed", error=str(exc))
        return last_published

    predictions_served.inc()
    return payload


async def _handle_row(
    row: dict[str, Any],
    model: ActiveModel,
    state: dict[int, _ReceiverState],
    window_size: int,
) -> bool:
    """Returns True if this row produced a new prediction vote."""
    csi_rows_consumed.inc()
    rid = row["receiver_id"]
    rs = state.setdefault(rid, _ReceiverState())
    rs.buf.append(row)

    if len(rs.buf) < window_size:
        return False

    start = time.perf_counter()
    try:
        room = _predict_once(model, rs.buf)
    except ValueError as exc:
        prediction_errors.labels(stage="extract").inc()
        log.warning("predict.extract_failed", receiver_id=rid, error=str(exc))
        rs.buf.clear()
        return False
    except Exception as exc:  # sklearn surface — vectorless predict edge cases
        prediction_errors.labels(stage="predict").inc()
        log.warning("predict.inference_failed", receiver_id=rid, error=str(exc))
        rs.buf.clear()
        return False
    finally:
        inference_duration_seconds.observe(time.perf_counter() - start)

    rs.buf.clear()
    rs.votes.append(room)
    return True


async def stream_loop(
    client: httpx.AsyncClient,
    holder: ModelHolder,
    stop: asyncio.Event,
    *,
    window_size: int = DEFAULT_WINDOW_SIZE,
    reconnect_backoff_s: float = 2.0,
) -> None:
    state: dict[int, _ReceiverState] = {}
    last_published: dict[str, Any] | None = None
    active_model_id: int | None = None

    while not stop.is_set():
        try:
            async with aconnect_sse(client, "GET", "/api/csi-stream") as source:
                log.info("stream.connected")
                async for event in source.aiter_sse():
                    if stop.is_set():
                        return
                    if event.event not in ("message", ""):
                        continue
                    try:
                        row = json.loads(event.data)
                    except json.JSONDecodeError:
                        continue

                    model = holder.current
                    if model is None:
                        # No active model yet; drop rows rather than buffering.
                        active_model_id = None
                        state.clear()
                        last_published = None
                        continue

                    if model.id != active_model_id:
                        # Drop buffered rows and vote history from the prior model.
                        active_model_id = model.id
                        state.clear()
                        last_published = None

                    changed = await _handle_row(row, model, state, window_size)
                    if changed:
                        votes = {rid: rs.votes for rid, rs in state.items()}
                        last_published = await _maybe_publish(client, model, votes, last_published)
        except httpx.HTTPError as exc:
            log.warning("stream.connection_lost", error=str(exc))
        except asyncio.CancelledError:
            raise

        try:
            await asyncio.wait_for(stop.wait(), timeout=reconnect_backoff_s)
            return
        except TimeoutError:
            continue
