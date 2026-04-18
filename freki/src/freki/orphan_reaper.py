"""Background task that reaps stuck training jobs and re-queues them.

Nornir stamps ``training_jobs.heartbeat_at`` every few seconds while it's
running a job. If a daemon crashes or loses the network, that timestamp goes
stale and the job is effectively orphaned. This task runs on a timer inside
Freki's lifespan, flips orphaned rows to ``failed`` with an explanatory
``error``, and inserts a fresh ``queued`` copy so another daemon can pick it
up.

Background tasks cannot rely on ``SessionDep`` (request scope) — they grab a
session from ``get_session_factory()`` directly.
"""

from __future__ import annotations

import asyncio
import os

import structlog
from csi_models import get_session_factory
from sqlalchemy import text

log = structlog.get_logger(__name__)

ORPHAN_CHECK_INTERVAL_S = float(os.environ.get("ORPHAN_CHECK_INTERVAL_S", "60"))
ORPHAN_TIMEOUT_S = float(os.environ.get("ORPHAN_TIMEOUT_S", "300"))


_REAP_SQL = text(
    """
    WITH reaped AS (
        UPDATE training_jobs
           SET status = 'failed',
               completed_at = NOW(),
               error = 'daemon heartbeat timeout',
               claim_token = NULL
         WHERE status = 'running'
           AND heartbeat_at IS NOT NULL
           AND heartbeat_at < NOW() - make_interval(secs => :timeout)
     RETURNING id, spec
    ),
    requeued AS (
        INSERT INTO training_jobs (spec)
        SELECT spec FROM reaped
        RETURNING id
    )
    SELECT
        COALESCE((SELECT array_agg(id) FROM reaped), ARRAY[]::integer[])   AS failed_ids,
        COALESCE((SELECT array_agg(id) FROM requeued), ARRAY[]::integer[]) AS requeued_ids
    """
)


async def _reap_once() -> None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(_REAP_SQL, {"timeout": ORPHAN_TIMEOUT_S})
        row = result.one()
        await session.commit()
    failed_ids = list(row.failed_ids or [])
    requeued_ids = list(row.requeued_ids or [])
    if failed_ids:
        log.warning(
            "orphan.jobs_reaped",
            failed_ids=failed_ids,
            requeued_ids=requeued_ids,
            timeout_s=ORPHAN_TIMEOUT_S,
        )


async def reaper_loop() -> None:
    """Forever loop. Cancel the task to stop it."""
    log.info(
        "orphan.reaper_started",
        interval_s=ORPHAN_CHECK_INTERVAL_S,
        timeout_s=ORPHAN_TIMEOUT_S,
    )
    try:
        while True:
            try:
                await _reap_once()
            except Exception as exc:  # noqa: BLE001 — don't die on transient DB errors
                log.error("orphan.reap_failed", error=str(exc))
            await asyncio.sleep(ORPHAN_CHECK_INTERVAL_S)
    except asyncio.CancelledError:
        log.info("orphan.reaper_stopped")
        raise
