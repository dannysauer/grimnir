"""Fixtures that drive Freki routers against a real, migrated database.

The routers are mounted on a bare FastAPI app instead of importing
``freki.main``, which reads ``DATABASE_URL`` at import time and starts the
orphan reaper. Each test gets its own engine, and Freki's real session
dependency runs against it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import freki.db
import httpx
import pytest
from csi_models import create_session_factory
from csi_models.migrate import run_migrations
from fastapi import FastAPI
from freki.routers import models, training_daemons, training_jobs
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool


@pytest.fixture(scope="session")
def migrated_database_url(make_database: Callable[[], str]) -> str:
    """One database per session with every bundled migration applied."""
    url = make_database()
    run_migrations(url)
    return url


@pytest.fixture
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    """A per-test engine over an emptied database.

    NullPool keeps connections from leaking across event loops. Every table
    in ``public`` except ``schema_migrations`` is truncated first, so no test
    sees another's rows, seeded rows included.
    """
    engine = create_async_engine(migrated_database_url, poolclass=NullPool)
    async with engine.begin() as conn:
        tables = (
            await conn.execute(
                text(
                    "SELECT quote_ident(tablename) FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename <> 'schema_migrations'"
                )
            )
        ).scalars()
        await conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
async def client(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client for the ML routers, backed by the test database.

    Only the session factory is swapped, and it comes from the same builder
    production uses, so the routes run with production session settings.
    """
    factory = create_session_factory(engine)
    monkeypatch.setattr(freki.db, "get_session_factory", lambda: factory)

    app = FastAPI()
    app.include_router(models.router, prefix="/api/models")
    app.include_router(training_daemons.router, prefix="/api/training-daemons")
    app.include_router(training_jobs.router, prefix="/api/training-jobs")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://freki.test") as http:
        yield http
