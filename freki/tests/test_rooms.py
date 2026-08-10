from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from conftest import FakeExecuteResult, FakeSession
from fastapi import HTTPException
from freki.routers import rooms
from sqlalchemy.exc import ProgrammingError


def _room(name: str, floor: int = 0) -> SimpleNamespace:
    return SimpleNamespace(name=name, floor=floor, created_at=datetime(2026, 6, 1, tzinfo=UTC))


@pytest.mark.asyncio
async def test_update_room_rename_rewrites_both_label_tables_atomically() -> None:
    session = FakeSession(
        execute_results=[
            FakeExecuteResult(scalar_value=_room("kitchen")),  # lookup by old name
            FakeExecuteResult(),  # SET LOCAL lock_timeout
            FakeExecuteResult(),  # SET LOCAL statement_timeout
            FakeExecuteResult(),  # UPDATE csi_samples
            FakeExecuteResult(),  # UPDATE training_samples (savepoint)
            FakeExecuteResult(scalar_value=_room("pantry")),  # re-query by new name
        ]
    )

    result = await rooms.update_room("kitchen", rooms.RoomUpdate(name="pantry"), session)

    assert result.name == "pantry"
    assert session.commits == 1
    assert session.nested_begins == 1
    statement, args, _ = session.execute_calls[4]
    assert "UPDATE training_samples" in str(statement)
    assert args[0] == {"new_name": "pantry", "old_name": "kitchen"}


@pytest.mark.asyncio
async def test_update_room_rename_survives_training_samples_permission_error() -> None:
    session = FakeSession(
        execute_results=[
            FakeExecuteResult(scalar_value=_room("kitchen")),
            FakeExecuteResult(),  # SET LOCAL lock_timeout
            FakeExecuteResult(),  # SET LOCAL statement_timeout
            FakeExecuteResult(),  # UPDATE csi_samples
            ProgrammingError(
                "UPDATE training_samples ...",
                {},
                Exception("permission denied for table training_samples"),
            ),
            FakeExecuteResult(scalar_value=_room("pantry")),
        ]
    )

    result = await rooms.update_room("kitchen", rooms.RoomUpdate(name="pantry"), session)

    assert result.name == "pantry"
    assert session.commits == 1


@pytest.mark.asyncio
async def test_update_room_rename_returns_503_on_lock_timeout() -> None:
    session = FakeSession(
        execute_results=[
            FakeExecuteResult(scalar_value=_room("kitchen")),
            FakeExecuteResult(),  # SET LOCAL lock_timeout
            FakeExecuteResult(),  # SET LOCAL statement_timeout
            ProgrammingError(
                "UPDATE csi_samples ...",
                {},
                Exception("canceling statement due to lock timeout"),
            ),
        ]
    )

    with pytest.raises(HTTPException) as excinfo:
        await rooms.update_room("kitchen", rooms.RoomUpdate(name="pantry"), session)

    assert excinfo.value.status_code == 503
    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_update_room_floor_only_change_skips_label_rewrites() -> None:
    session = FakeSession(
        execute_results=[
            FakeExecuteResult(scalar_value=_room("kitchen", floor=0)),
            FakeExecuteResult(scalar_value=_room("kitchen", floor=1)),
        ]
    )

    result = await rooms.update_room("kitchen", rooms.RoomUpdate(floor=1), session)

    assert result.floor == 1
    assert session.commits == 1
    assert session.nested_begins == 0
    assert len(session.execute_calls) == 2  # lookup + re-query only
