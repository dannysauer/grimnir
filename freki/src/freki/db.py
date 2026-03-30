"""
db.py — shared asyncpg pool for Freki.

Usage in a router:
    from ..db import get_pool
    pool = get_pool()
    rows = await pool.fetch("SELECT ...")
"""

from __future__ import annotations

import asyncpg

_pool: asyncpg.Pool | None = None


async def init_pool(dsn: str) -> None:
    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=20)


async def close_pool() -> None:
    if _pool:
        await _pool.close()


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized — startup event not fired?")
    return _pool
