from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import FakeExecuteResult, FakeSession
from csi_models import CsiSample
from freki.routers import training_data
from sqlalchemy.exc import ProgrammingError


def _sample() -> CsiSample:
    return CsiSample(
        time=datetime(2026, 4, 19, 19, 20, tzinfo=UTC),
        receiver_id=6,
        transmitter_mac="aa:bb:cc:dd:ee:ff",
        rssi=-55,
        noise_floor=-95,
        channel=1,
        bandwidth=20,
        antenna_count=2,
        subcarrier_count=64,
        amplitude=[1.0, 2.0],
        phase=[0.1, 0.2],
        raw_bytes=None,
        label="kitchen",
    )


@pytest.mark.asyncio
async def test_get_training_data_falls_back_to_csi_samples_when_training_samples_is_unreadable() -> (
    None
):
    session = FakeSession(
        execute_results=[
            ProgrammingError(
                "SELECT * FROM training_samples",
                {},
                Exception("permission denied for table training_samples"),
            ),
            FakeExecuteResult(scalars_values=[_sample()]),
        ]
    )

    page = await training_data.get_training_data(
        session,
        time_start=datetime(2026, 4, 19, 19, 0, tzinfo=UTC),
        time_end=datetime(2026, 4, 19, 20, 0, tzinfo=UTC),
        rooms="kitchen",
    )

    assert session.rollbacks == 1
    assert page.next_cursor is None
    assert len(page.rows) == 1
    assert page.rows[0].label == "kitchen"
