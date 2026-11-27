"""Async SQLAlchemy engine and session helpers."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> AsyncEngine:
    """Initialise the shared async engine and session factory."""
    global _engine, _session_factory

    if _engine is not None:
        return _engine

    _engine = create_async_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
    )
    _session_factory = create_session_factory(_engine)
    return _engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build the session factory every service uses for ``engine``.

    Objects stay readable after commit (``expire_on_commit=False``); route
    handlers rely on that to read generated ids without another query.
    """
    return async_sessionmaker(engine, expire_on_commit=False)


def get_engine() -> AsyncEngine:
    """Return the initialised async engine."""
    if _engine is None:
        raise RuntimeError("Database engine has not been initialised")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the initialised async session factory."""
    if _session_factory is None:
        raise RuntimeError("Session factory has not been initialised")
    return _session_factory
