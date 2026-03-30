"""
main.py — CSI Backend (FastAPI)

Startup sequence:
  1. Run Alembic migrations (idempotent)
  2. Initialise SQLAlchemy async engine
  3. Serve FastAPI via uvicorn

Environment variables:
  DATABASE_URL  postgresql+asyncpg://user:pass@host:5432/csi
  HOST          bind address (default 0.0.0.0)
  PORT          bind port (default 8000)
  LOG_LEVEL     debug | info | warning | error (default info)
"""

from __future__ import annotations

import logging
import os

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from csi_models import get_engine, init_engine, run_migrations

from .routers import history, labels, stream

DATABASE_URL = os.environ["DATABASE_URL"]
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info")
FRONTEND_DIR = os.environ.get("FRONTEND_DIR", "/app/frontend")

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    )
)
log = structlog.get_logger(__name__)

app = FastAPI(title="CSI Localization API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stream.router, prefix="/api")
app.include_router(history.router, prefix="/api/history")
app.include_router(labels.router, prefix="/api/labels")


@app.get("/health")
async def health():
    return {"status": "ok"}


# Serve frontend static files if the directory exists
import pathlib

_frontend = pathlib.Path(FRONTEND_DIR)
if _frontend.exists():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")


@app.on_event("startup")
async def startup() -> None:
    log.info("backend.starting")
    log.info("migrations.running")
    run_migrations(DATABASE_URL)
    log.info("migrations.done")
    init_engine(DATABASE_URL)
    log.info("db.engine_initialised")


@app.on_event("shutdown")
async def shutdown() -> None:
    engine = get_engine()
    await engine.dispose()
    log.info("backend.stopped")


def run() -> None:
    uvicorn.run(
        "freki.main:app",
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL,
        reload=False,
    )


if __name__ == "__main__":
    run()
