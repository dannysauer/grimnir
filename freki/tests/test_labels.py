from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from conftest import FakeExecuteResult, FakeSession
from fastapi import BackgroundTasks, HTTPException
from freki.routers import labels
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError, ProgrammingError


def _label(label_id: int, start: datetime, end: datetime, room: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=label_id,
        time_start=start,
        time_end=end,
        room=room,
        created_at=start,
    )


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


@pytest.mark.asyncio
async def test_delete_label_commits_cleanup_then_resyncs() -> None:
    start = datetime(2026, 4, 19, 19, 0, tzinfo=UTC)
    end = datetime(2026, 4, 19, 20, 0, tzinfo=UTC)
    label = _label(7, start, end, "kitchen")
    session = FakeSession(
        execute_results=[
            FakeExecuteResult(scalar_value=label),  # label lookup
            FakeExecuteResult(),  # SET LOCAL lock_timeout
            FakeExecuteResult(),  # SET LOCAL statement_timeout
            FakeExecuteResult(),  # clear window UPDATE
            FakeExecuteResult(scalars_values=[]),  # overlap query
            # resync (post-commit): SET LOCAL x2, DELETE, then insert helper
            # re-sets timeouts (x2) and runs INSERT
            FakeExecuteResult(),
            FakeExecuteResult(),
            FakeExecuteResult(),  # DELETE FROM training_samples
            FakeExecuteResult(),
            FakeExecuteResult(),
            FakeExecuteResult(),  # INSERT INTO training_samples
        ]
    )

    await labels.delete_label(7, session)

    assert session.deleted == [label]
    assert session.commits == 2  # cleanup transaction + resync transaction


@pytest.mark.asyncio
async def test_delete_label_returns_503_on_lock_timeout() -> None:
    start = datetime(2026, 4, 19, 19, 0, tzinfo=UTC)
    end = datetime(2026, 4, 19, 20, 0, tzinfo=UTC)
    session = FakeSession(
        execute_results=[
            FakeExecuteResult(scalar_value=_label(7, start, end, "kitchen")),
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
        await labels.delete_label(7, session)

    assert excinfo.value.status_code == 503
    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_delete_label_resync_never_raises_after_commit() -> None:
    # A timeout in the post-commit training_samples resync must not surface
    # as a 500 for a delete that already succeeded (#64).
    session = FakeSession(
        execute_results=[
            FakeExecuteResult(),  # SET LOCAL lock_timeout
            FakeExecuteResult(),  # SET LOCAL statement_timeout
            ProgrammingError(
                "DELETE FROM training_samples ...",
                {},
                Exception("canceling statement due to lock timeout"),
            ),
        ]
    )

    await labels._resync_training_samples_best_effort(
        session,
        datetime(2026, 4, 19, 19, 0, tzinfo=UTC),
        datetime(2026, 4, 19, 20, 0, tzinfo=UTC),
    )

    assert session.commits == 0
    assert session.rollbacks == 1
