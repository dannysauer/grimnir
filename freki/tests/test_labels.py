from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import FakeExecuteResult, FakeSession
from fastapi import BackgroundTasks, HTTPException
from freki.routers import labels
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError, ProgrammingError


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
        await labels.create_label(body, BackgroundTasks(), session)

    assert session.rollbacks == 1
    assert session.flushes == 1


@pytest.mark.asyncio
async def test_create_label_commits_label_before_scheduling_backfill() -> None:
    class RefreshedLabelSession(FakeSession):
        async def refresh(self, obj: object) -> None:
            await super().refresh(obj)
            obj.id = 123
            obj.created_at = datetime(2026, 4, 19, 19, 16, 13, 400000, tzinfo=UTC)

    session = RefreshedLabelSession()
    background_tasks = BackgroundTasks()
    body = labels.LabelCreate(
        time_start=datetime(2026, 4, 19, 19, 16, 3, 348000, tzinfo=UTC),
        time_end=datetime(2026, 4, 19, 19, 16, 13, 311000, tzinfo=UTC),
        room="kitchen",
        occupants=1,
    )

    label = await labels.create_label(body, background_tasks, session)

    assert isinstance(label, labels.LabelOut)
    assert label.room == "kitchen"
    assert session.commits == 1
    assert session.refreshes == 1
    assert session.execute_calls == []
    assert len(background_tasks.tasks) == 1


@pytest.mark.asyncio
async def test_sync_training_samples_succeeds_when_permission_is_denied() -> None:
    session = FakeSession(
        execute_results=[
            FakeExecuteResult(),
            FakeExecuteResult(),
            ProgrammingError(
                "INSERT INTO training_samples ...",
                {},
                Exception("permission denied for table training_samples"),
            ),
        ]
    )

    await labels._sync_training_samples_best_effort(
        session,
        datetime(2026, 4, 19, 19, 16, 3, 348000, tzinfo=UTC),
        datetime(2026, 4, 19, 19, 16, 13, 311000, tzinfo=UTC),
    )

    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_csi_backfill_is_bounded_best_effort() -> None:
    session = FakeSession(
        execute_results=[
            FakeExecuteResult(),
            FakeExecuteResult(),
            ProgrammingError(
                "UPDATE csi_samples ...",
                {},
                Exception("canceling statement due to lock timeout"),
            ),
        ]
    )

    backfilled = await labels._backfill_csi_samples_best_effort(
        session,
        datetime(2026, 4, 19, 19, 16, 3, 348000, tzinfo=UTC),
        datetime(2026, 4, 19, 19, 16, 13, 311000, tzinfo=UTC),
        "kitchen",
    )

    assert backfilled is False
    assert session.commits == 0
    assert session.rollbacks == 1
