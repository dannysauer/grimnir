"""
backfill.py

Shared guard rails for bulk writes that touch the csi_samples hypertable.

Bulk UPDATEs over csi_samples can block behind TimescaleDB compression
locks (#49), so every such write runs with SET LOCAL timeouts. A write that
can't finish inside the budget is cancelled by Postgres and surfaces as a
DBAPIError, which the caller maps to a retryable error rather than hanging
the request.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

BACKFILL_LOCK_TIMEOUT = "2s"
BACKFILL_STATEMENT_TIMEOUT = "15s"


async def set_backfill_timeouts(session: AsyncSession) -> None:
    """Bound lock and statement waits for the current transaction."""
    await session.execute(text(f"SET LOCAL lock_timeout = '{BACKFILL_LOCK_TIMEOUT}'"))
    await session.execute(text(f"SET LOCAL statement_timeout = '{BACKFILL_STATEMENT_TIMEOUT}'"))
