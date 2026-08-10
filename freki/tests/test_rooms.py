from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from conftest import FakeExecuteResult, FakeSession
from freki.routers import rooms
from sqlalchemy.exc import ProgrammingError


def _room(name: str, floor: int = 0) -> SimpleNamespace:
    return SimpleNamespace(name=name, floor=floor, created_at=datetime(2026, 6, 1, tzinfo=UTC))


@pytest.mark.asyncio
async def test_update_room_rename_rewrites_training_samples_label() -> None:
    session = FakeSession(
        execute_results=[
            FakeExecuteResult(scalar_value=_room("kitchen")),  # lookup by old name
            FakeExecuteResult(),  # UPDATE csi_samples
            FakeExecuteResult(),  # UPDATE training_samples
            FakeExecuteResult(scalar_value=_room("pantry")),  # re-query by new name
        ]
    )
    body = rooms.RoomUpdate(name="pantry")

    result = await rooms.update_room("kitchen", body, session)

    assert result.name == "pantry"
    assert session.commits == 1
    assert session.nested_begins == 1
    statement, args, _ = session.execute_calls[2]
    assert "UPDATE training_samples" in str(statement)
    assert args[0] == {"new_name": "pantry", "old_name": "kitchen"}


@pytest.mark.asyncio
async def test_update_room_rename_survives_training_samples_permission_error() -> None:
    session = FakeSession(
        execute_results=[
            FakeExecuteResult(scalar_value=_room("kitchen")),
            FakeExecuteResult(),  # UPDATE csi_samples
            ProgrammingError(
                "UPDATE training_samples ...",
                {},
                Exception("permission denied for table training_samples"),
            ),
            FakeExecuteResult(scalar_value=_room("pantry")),
        ]
    )
    body = rooms.RoomUpdate(name="pantry")

    result = await rooms.update_room("kitchen", body, session)

    assert result.name == "pantry"
    assert session.commits == 1


@pytest.mark.asyncio
async def test_update_room_floor_only_change_skips_label_rewrites() -> None:
    session = FakeSession(
        execute_results=[
            FakeExecuteResult(scalar_value=_room("kitchen", floor=0)),
            FakeExecuteResult(scalar_value=_room("kitchen", floor=1)),
        ]
    )
    body = rooms.RoomUpdate(floor=1)

    result = await rooms.update_room("kitchen", body, session)

    assert result.floor == 1
    assert session.commits == 1
    assert session.nested_begins == 0
    assert len(session.execute_calls) == 2
