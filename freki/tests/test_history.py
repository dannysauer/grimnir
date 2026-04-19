from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import FakeExecuteResult, FakeSession
from freki.routers import history


@pytest.mark.asyncio
async def test_get_variance_uses_bound_cutoff_for_aggregate_query() -> None:
    session = FakeSession(
        execute_results=[
            FakeExecuteResult(
                mappings_values=[
                    {
                        "time": datetime(2026, 4, 19, 19, 0, tzinfo=UTC),
                        "avg_rssi": -55.4,
                        "stddev_rssi": 1.2345,
                        "sample_count": 12,
                    },
                    {
                        "time": datetime(2026, 4, 19, 19, 1, tzinfo=UTC),
                        "avg_rssi": -56.1,
                        "stddev_rssi": 1.1111,
                        "sample_count": 10,
                    },
                ]
            )
        ]
    )

    rows = await history.get_variance(session, receiver_id=6, minutes=60)

    assert len(rows) == 2
    assert rows[0]["avg_rssi"] == -55.4
    _, args, _ = session.execute_calls[0]
    params = args[0]
    assert params["rx_id"] == 6
    assert isinstance(params["cutoff"], datetime)


@pytest.mark.asyncio
async def test_get_variance_falls_back_to_raw_query_with_same_cutoff() -> None:
    session = FakeSession(
        execute_results=[
            FakeExecuteResult(mappings_values=[]),
            FakeExecuteResult(
                mappings_values=[
                    {
                        "time": datetime(2026, 4, 19, 19, 2, tzinfo=UTC),
                        "avg_rssi": -57.0,
                        "stddev_rssi": 0.5,
                        "sample_count": 3,
                    }
                ]
            ),
        ]
    )

    rows = await history.get_variance(session, receiver_id=7, minutes=30)

    assert rows == [
        {
            "time": "2026-04-19T19:02:00+00:00",
            "avg_rssi": -57.0,
            "stddev_rssi": 0.5,
            "sample_count": 3,
        }
    ]
    _, first_args, _ = session.execute_calls[0]
    _, second_args, _ = session.execute_calls[1]
    assert first_args[0]["cutoff"] == second_args[0]["cutoff"]
