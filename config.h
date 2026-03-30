"""
main.py — CSI Backend (FastAPI)

Configuration via environment variables:
  DATABASE_URL   — asyncpg DSN
  HOST           — bind host (default 0.0.0.0)
  PORT           — bind port (default 8000)
  LOG_LEVEL      — debug | info | warning (default info)
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

log = structlog.get_logger(__name__)

app = FastAPI(title="CSI Localization API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stream.router,  prefix="/api")
app.include_router(history.router, prefix="/api/history")
app.include_router(labels.router,  prefix="/api/labels")

# Serve the frontend's index.html from /static
# In production this should be behind nginx, but this works for development
STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "frontend")
if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


@app.on_event("startup")
async def startup():
    await init_pool(DATABASE_URL)
    log.info("backend.started", port=PORT)


@app.on_event("shutdown")
async def shutdown():
    await close_pool()


@app.get("/health")
async def health():
    return {"status": "ok"}


def run() -> None:
    uvicorn.run(
        "csi_backend.main:app",
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL,
        reload=False,
    )


if __name__ == "__main__":
    run()
