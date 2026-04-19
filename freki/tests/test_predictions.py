from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from conftest import FakeExecuteResult, FakeSession, FakeSessionFactory
from fastapi import HTTPException
from freki.routers import predictions
from sqlalchemy.dialects import postgresql


def _payload() -> dict[str, object]:
    return {
        "timestamp": "2026-04-18T20:00:00+00:00",
        "model_id": 7,
        "rooms": {"living_room": {"human_count": 1}},
    }


@pytest.mark.asyncio
async def test_put_current_upserts_singleton_prediction_row() -> None:
    session = FakeSession(execute_results=[FakeExecuteResult()])
    body = predictions.PredictionUpdate.model_validate(_payload())

    await predictions.put_current(body, session)

    assert session.commits == 1
    statement, _, _ = session.execute_calls[0]
    params = statement.compile(dialect=postgresql.dialect()).params
    assert params["id"] == predictions.PREDICTION_ROW_ID
    assert params["payload"] == body.model_dump(mode="json")


@pytest.mark.asyncio
async def test_get_current_returns_latest_snapshot() -> None:
    session = FakeSession(execute_results=[FakeExecuteResult(scalar_value=_payload())])

    snapshot = await predictions.get_current(session)

    assert snapshot == _payload()


@pytest.mark.asyncio
async def test_get_current_raises_404_when_empty() -> None:
    session = FakeSession(execute_results=[FakeExecuteResult(scalar_value=None)])

    with pytest.raises(HTTPException, match="No prediction available"):
        await predictions.get_current(session)


@pytest.mark.asyncio
async def test_event_generator_emits_shared_prediction_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updated_at = datetime(2026, 4, 18, 20, 0, tzinfo=UTC)
    snapshot = SimpleNamespace(payload=_payload(), updated_at=updated_at)
    factory = FakeSessionFactory(
        [FakeSession(execute_results=[FakeExecuteResult(one_value=snapshot)])]
    )
    monkeypatch.setattr(predictions, "get_session_factory", lambda: factory)

    generator = predictions._event_generator()
    try:
        event = await anext(generator)
    finally:
        await generator.aclose()

    assert event == f"data: {json.dumps(_payload())}\n\n"
