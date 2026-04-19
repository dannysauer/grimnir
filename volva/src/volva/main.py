"""
main.py — Völva CSI inference service (FastAPI).

Starts two background tasks in the lifespan:

  1. ``model_loader.refresh_loop`` — polls Freki ``/api/models/active`` every
     ``MODEL_REFRESH_S`` seconds and hot-swaps the in-memory classifier when
     the active model id changes. Refuses models whose
     ``feature_config.version`` mismatches this build's FEATURE_VERSION.
  2. ``predict.stream_loop`` — subscribes to Freki ``/api/csi-stream``, windows
     per-receiver CSI, runs the classifier, and publishes the
     ``{timestamp, model_id, rooms}`` envelope via
     ``PUT /api/predictions/current``.

The service itself exposes only ``/health`` and ``/metrics`` — Völva writes to
Freki rather than serving a public prediction API. Home Assistant polls
Freki's ``GET /api/predictions/current`` directly.

Label carve-out (plan A2): the v1 training target is the ``label`` column
(room name). A predicted room is reported as ``human_count=1`` with all
other known rooms at 0. Pets are currently included in ``labels.occupants``
— see issue #14.

Environment variables:
  FREKI_URL         base URL for Freki (default http://freki:8000)
  HOST              bind address (default 0.0.0.0)
  PORT              bind port (default 8002)
  WINDOW_SIZE       rows per prediction window (default 50)
  MODEL_REFRESH_S   active-model poll interval (default 30)
  LOG_LEVEL         debug | info | warning | error (default info)
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import httpx
import structlog
import uvicorn
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from .metrics import active_model_age_seconds, active_model_id
from .model_loader import ModelHolder, refresh_loop
from .predict import stream_loop

FREKI_URL = os.environ.get("FREKI_URL", "http://freki:8000")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8002"))
WINDOW_SIZE = int(os.environ.get("WINDOW_SIZE", "50"))
MODEL_REFRESH_S = float(os.environ.get("MODEL_REFRESH_S", "30"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").upper()

_log_level_int = getattr(logging, LOG_LEVEL, logging.INFO)
_shared_processors = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.StackInfoRenderer(),
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.ExceptionRenderer(),
]
structlog.configure(
    processors=[
        *_shared_processors,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.make_filtering_bound_logger(_log_level_int),
    context_class=dict,
    cache_logger_on_first_use=True,
)
_handler = logging.StreamHandler()
_handler.setFormatter(
    structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=_shared_processors,
    )
)
logging.root.handlers = [_handler]
logging.root.setLevel(_log_level_int)
log = structlog.get_logger(__name__)


async def _update_model_gauges(holder: ModelHolder, stop: asyncio.Event) -> None:
    """Keep the active-model gauges fresh so Prometheus sees current age."""
    while not stop.is_set():
        model = holder.current
        active_model_id.set(model.id if model else 0)
        active_model_age_seconds.set(holder.age_seconds())
        try:
            await asyncio.wait_for(stop.wait(), timeout=5.0)
            return
        except TimeoutError:
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("volva.starting", freki=FREKI_URL, window_size=WINDOW_SIZE)

    holder = ModelHolder()
    app.state.model_holder = holder
    stop_event = asyncio.Event()
    app.state.stop_event = stop_event

    # Long timeout for the SSE client; short for everything else.
    app.state.http = httpx.AsyncClient(base_url=FREKI_URL, timeout=None)

    tasks = [
        asyncio.create_task(refresh_loop(app.state.http, holder, MODEL_REFRESH_S, stop_event)),
        asyncio.create_task(
            stream_loop(app.state.http, holder, stop_event, window_size=WINDOW_SIZE)
        ),
        asyncio.create_task(_update_model_gauges(holder, stop_event)),
    ]
    app.state.tasks = tasks
    log.info("volva.ready")

    try:
        yield
    finally:
        log.info("volva.stopping")
        stop_event.set()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await app.state.http.aclose()
        log.info("volva.stopped")


app = FastAPI(title="Völva CSI Inference", version="0.1.0", lifespan=lifespan)

Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    excluded_handlers=["/health", "/metrics"],
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.get("/health")
async def health() -> dict[str, object]:
    holder: ModelHolder = app.state.model_holder
    model = holder.current
    return {
        "status": "ok",
        "model_id": model.id if model else None,
        "model_age_seconds": holder.age_seconds(),
    }


def run() -> None:
    uvicorn.run(
        "volva.main:app",
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        log_config=None,  # preserve our structlog stdlib bridge; uvicorn default overrides it
        access_log=False,
        reload=False,
    )


if __name__ == "__main__":
    run()
