"""
main.py — Völva inference service

Startup sequence:
  1. Fetch active model from Freki; hot-reload when active model changes
  2. Subscribe to Freki SSE stream; apply model to each snapshot
  3. Push predictions to Freki; also serve them via local API

Environment variables:
  FREKI_URL              http://freki:8000
  HOST                   bind address (default 0.0.0.0)
  PORT                   bind port (default 8002)
  MODEL_POLL_INTERVAL_S  how often to check for a new active model (default 60)
  LOG_LEVEL              debug | info | warning | error (default info)
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import joblib
import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import state
from .client import FrekiClient
from .predict import predict_room_occupancy, validate_feature_config

FREKI_URL = os.environ["FREKI_URL"]
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8002"))
MODEL_POLL_INTERVAL_S = int(os.environ.get("MODEL_POLL_INTERVAL_S", "60"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info")

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)
log = structlog.get_logger(__name__)


async def _load_active_model(client: FrekiClient) -> None:
    """Fetch and deserialize the active model from Freki."""
    meta = await client.get_active_model_metadata()
    if meta is None:
        log.info("model.none_active")
        return

    model_id = meta["id"]
    if model_id == state.active_model_id:
        return

    feature_config = meta.get("feature_config", {})
    try:
        validate_feature_config(feature_config)
    except ValueError as exc:
        log.warning("model.incompatible_feature_config", model_id=model_id, error=str(exc))
        return

    model_bytes = await client.download_model_bytes(model_id)
    model = await asyncio.to_thread(joblib.load, io.BytesIO(model_bytes))
    state.active_model_id = model_id
    state.active_model = model
    log.info("model.loaded", model_id=model_id, accuracy=meta.get("metrics", {}).get("accuracy"))


async def _model_watcher(client: FrekiClient) -> None:
    """Periodically check for a new active model and hot-reload if changed."""
    while True:
        await asyncio.sleep(MODEL_POLL_INTERVAL_S)
        try:
            await _load_active_model(client)
        except Exception:
            log.warning("model_watcher.error")


async def _inference_loop(client: FrekiClient) -> None:
    """Subscribe to Freki SSE and push predictions on each snapshot."""
    while True:
        try:
            async for snapshot in client.stream_csi():
                if state.active_model is None:
                    continue
                try:
                    rooms_pred = await asyncio.to_thread(
                        predict_room_occupancy, state.active_model, snapshot
                    )
                    if not rooms_pred:
                        continue
                    payload = {
                        "timestamp": datetime.now(tz=UTC).isoformat(),
                        "model_id": state.active_model_id,
                        "rooms": rooms_pred,
                    }
                    state.latest_predictions = payload
                    await client.push_predictions(payload)
                except Exception:
                    log.warning("inference.predict_error")
        except Exception:
            log.warning("inference.stream_error")
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("volva.starting")
    client = FrekiClient(base_url=FREKI_URL)
    try:
        await _load_active_model(client)
    except Exception:
        log.warning("volva.initial_model_load_failed")

    watcher_task = asyncio.create_task(_model_watcher(client))
    inference_task = asyncio.create_task(_inference_loop(client))
    log.info("volva.started")
    yield
    watcher_task.cancel()
    inference_task.cancel()
    await client.aclose()
    log.info("volva.stopped")


app = FastAPI(title="Völva Inference API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "model_id": state.active_model_id}


@app.get("/api/predictions/current")
async def get_predictions():
    """Current room occupancy predictions (for Home Assistant REST sensor)."""
    return state.latest_predictions


async def _sse_generator():
    while True:
        if state.latest_predictions:
            yield f"data: {json.dumps(state.latest_predictions)}\n\n"
        await asyncio.sleep(1)


@app.get("/api/predictions/stream")
async def stream_predictions():
    """SSE stream of live predictions."""
    return StreamingResponse(
        _sse_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def run() -> None:
    uvicorn.run(
        "volva.main:app",
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        access_log=False,
        reload=False,
    )


if __name__ == "__main__":
    run()
