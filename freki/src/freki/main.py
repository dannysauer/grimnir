"""
main.py — Freki (CSI Backend, FastAPI)

Startup sequence:
  1. Connect asyncpg pool to TimescaleDB
  2. Serve FastAPI via uvicorn

Environment variables:
  DATABASE_URL  postgresql://user:pass@host:5432/csi  (required)
  HOST          bind address (default 0.0.0.0)
  PORT          bind port (default 8000)
  FRONTEND_DIR  path to hlidskjalf static files (default /app/frontend)
  LOG_LEVEL     debug | info | warning | error (default info)
"""

from __future__ import annotations

import os

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .db import close_pool, init_pool
from .routers import history, labels, stream

DATABASE_URL = os.environ["DATABASE_URL"]
HOST         = os.environ.get("HOST", "0.0.0.0")
PORT         = int(os.environ.get("PORT", "8000"))
LOG_LEVEL    = os.environ.get("LOG_LEVEL", "info")
FRONTEND_DIR = os.environ.get("FRONTEND_DIR", "/app/frontend")

log = structlog.get_logger(__name__)

app = FastAPI(title="Grimnir CSI API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stream.router,  prefix="/api")
app.include_router(history.router, prefix="/api/history")
app.include_router(labels.router,  prefix="/api/labels")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.on_event("startup")
async def startup() -> None:
    await init_pool(DATABASE_URL)
    log.info("freki.started", port=PORT)

    # Serve hlidskjalf (frontend) if the directory exists
    import pathlib
    if pathlib.Path(FRONTEND_DIR).exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="hlidskjalf")


@app.on_event("shutdown")
async def shutdown() -> None:
    await close_pool()
    log.info("freki.stopped")


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
