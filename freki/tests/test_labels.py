from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import FakeExecuteResult, FakeSession
from fastapi import HTTPException
from freki.routers import labels
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError


@pytest.mark.asyncio
async def test_list_labels_uses_bound_cutoff_parameter() -> None:
    session = FakeSession(execute_results=[FakeExecuteResult(scalars_values=[])])

    result = await labels.list_labels(session, minutes=120)

    assert result == []
    statement, _, _ = session.execute_calls[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "labels.time_end >=" in str(compiled)
    assert any(isinstance(value, datetime) for value in compiled.params.values())


@pytest.mark.asyncio
async def test_create_label_rolls_back_when_room_is_unknown() -> None:
    session = FakeSession(flush_exception=IntegrityError("stmt", "params", Exception("fk")))
    body = labels.LabelCreate(
        time_start=datetime(2026, 4, 18, 19, 0, tzinfo=UTC),
        time_end=datetime(2026, 4, 18, 20, 0, tzinfo=UTC),
        room="garage",
        occupants=1,
    )

    with pytest.raises(HTTPException, match="does not exist"):
        await labels.create_label(body, session)

    assert session.rollbacks == 1
    assert session.flushes == 1
