"""
main.py — CSI Backend (FastAPI)

Startup sequence:
  1. Run bundled SQL bootstrap migrations (idempotent)
  2. Initialise SQLAlchemy async engine
  3. Start background tasks (orphan reaper)
  4. Serve FastAPI via uvicorn

Environment variables:
  DATABASE_URL               postgresql+asyncpg://user:pass@host:5432/csi
  HOST                       bind address (default 0.0.0.0)
  PORT                       bind port (default 8000)
  LOG_LEVEL                  debug | info | warning | error (default info)
  MODEL_UPLOAD_SHARED_SECRET optional shared secret required for POST /api/models
  ML_CONTROL_SHARED_SECRET   optional shared secret required for daemon/job ML writes
  ORPHAN_CHECK_INTERVAL_S    reaper poll interval (default 60)
  ORPHAN_TIMEOUT_S           training job heartbeat timeout (default 300)
  CSI_STREAM_INTERVAL_MS     /api/csi-stream poll interval (default 200)
  CSI_STREAM_MAX_BATCH       /api/csi-stream max rows per tick (default 200)
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
from contextlib import asynccontextmanager

import structlog
import uvicorn
from csi_models import get_engine, init_engine, run_migrations
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from .orphan_reaper import reaper_loop
from .routers import (
    csi_stream,
    history,
    labels,
    models,
    predictions,
    rooms,
    stream,
    training_daemons,
    training_data,
    training_jobs,
)

DATABASE_URL = os.environ["DATABASE_URL"]
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info")
FRONTEND_DIR = os.environ.get("FRONTEND_DIR", "/app/frontend")

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("backend.starting")
    log.info("migrations.running")
    run_migrations(DATABASE_URL)
    log.info("migrations.done")
    init_engine(DATABASE_URL)
    log.info("db.engine_initialised")

    app.state.orphan_reaper_task = asyncio.create_task(reaper_loop())

    yield

    app.state.orphan_reaper_task.cancel()
    try:
        await app.state.orphan_reaper_task
    except asyncio.CancelledError:
        pass

    engine = get_engine()
    await engine.dispose()
    log.info("backend.stopped")


app = FastAPI(title="CSI Localization API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stream.router, prefix="/api")
app.include_router(csi_stream.router, prefix="/api/csi-stream")
app.include_router(history.router, prefix="/api/history")
app.include_router(labels.router, prefix="/api/labels")
app.include_router(rooms.router, prefix="/api/rooms")
app.include_router(training_daemons.router, prefix="/api/training-daemons")
app.include_router(training_jobs.router, prefix="/api/training-jobs")
app.include_router(training_data.router, prefix="/api/training-data")
app.include_router(models.router, prefix="/api/models")
app.include_router(predictions.router, prefix="/api/predictions")

# Instrument all HTTP endpoints and expose /metrics.
# Health and metrics endpoints are excluded from request duration tracking.
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    excluded_handlers=["/health", "/metrics"],
).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.get("/health")
async def health():
    return {"status": "ok"}


_frontend = pathlib.Path(FRONTEND_DIR)
if _frontend.exists():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")


def run() -> None:
    uvicorn.run(
        "freki.main:app",
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        access_log=False,  # request metrics are handled by Prometheus instrumentator
        reload=False,
    )


if __name__ == "__main__":
    run()
