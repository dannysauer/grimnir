"""
db.py — FastAPI dependency for SQLAlchemy async sessions.

Usage in a router:
    from ..db import SessionDep
    async def my_endpoint(session: SessionDep): ...
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from csi_models import get_session_factory
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession


async def _get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(_get_session)]
