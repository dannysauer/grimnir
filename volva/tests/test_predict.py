from __future__ import annotations

from collections import deque
from datetime import UTC, datetime

import pytest
from volva.model_loader import ActiveModel

from volva import predict


def _model(classes: list[str]) -> ActiveModel:
    return ActiveModel(
        id=1,
        name="test",
        classifier=object(),
        feature_config=object(),
        classes=classes,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )


def test_aggregate_marks_every_receiver_winner_present() -> None:
    votes = {
        1: deque(["kitchen", "kitchen", "garage"]),
        2: deque(["garage"]),
    }
    rooms = predict._aggregate(votes, ["kitchen", "garage", "attic"])

    assert rooms == {
        "kitchen": {"human_count": 1},
        "garage": {"human_count": 1},
        "attic": {"human_count": 0},
    }


def test_aggregate_empty_history_reports_all_zero() -> None:
    rooms = predict._aggregate({1: deque()}, ["kitchen", "garage"])
    assert rooms == {"kitchen": {"human_count": 0}, "garage": {"human_count": 0}}


@pytest.mark.asyncio
async def test_handle_row_rejects_row_without_receiver_id() -> None:
    state: dict[int, predict._ReceiverState] = {}

    changed = await predict._handle_row({"rssi": -40}, _model(["kitchen"]), state, window_size=5)

    assert changed is False
    assert state == {}


@pytest.mark.asyncio
async def test_handle_row_buffers_until_window_is_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(predict, "_predict_once", lambda model, buf: "kitchen")
    model = _model(["kitchen", "garage"])
    state: dict[int, predict._ReceiverState] = {}

    for _ in range(2):
        assert await predict._handle_row({"receiver_id": 7}, model, state, window_size=3) is False
    assert len(state[7].buf) == 2

    changed = await predict._handle_row({"receiver_id": 7}, model, state, window_size=3)

    assert changed is True
    assert state[7].buf == []  # window consumed
    assert list(state[7].votes) == ["kitchen"]


@pytest.mark.asyncio
async def test_handle_row_clears_window_on_extract_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(model: object, buf: object) -> str:
        raise ValueError("inconsistent window width")

    monkeypatch.setattr(predict, "_predict_once", _boom)
    model = _model(["kitchen"])
    state = {7: predict._ReceiverState()}
    state[7].buf = [{"receiver_id": 7}, {"receiver_id": 7}]

    changed = await predict._handle_row({"receiver_id": 7}, model, state, window_size=3)

    assert changed is False
    assert state[7].buf == []  # window dropped so a bad frame can't wedge it
    assert list(state[7].votes) == []
