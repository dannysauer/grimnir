from __future__ import annotations

from datetime import UTC, datetime
from ipaddress import ip_address

import pytest
from conftest import FakeExecuteResult, FakeSession
from csi_models import TrainingDaemon
from freki.routers import training_daemons


def _daemon(*, ip: str) -> TrainingDaemon:
    return TrainingDaemon(
        id=7,
        name="nornir-a",
        host="humpy",
        ip_address=ip_address(ip),
        capabilities={"gpu": []},
        last_seen=datetime(2026, 4, 19, 19, 0, tzinfo=UTC),
        created_at=datetime(2026, 4, 19, 18, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_list_daemons_serializes_ip_address_objects() -> None:
    session = FakeSession(
        execute_results=[FakeExecuteResult(scalars_values=[_daemon(ip="10.42.1.112")])]
    )

    rows = await training_daemons.list_daemons(session)

    assert len(rows) == 1
    assert rows[0].ip_address == "10.42.1.112"


@pytest.mark.asyncio
async def test_heartbeat_serializes_ip_address_objects() -> None:
    session = FakeSession(
        execute_results=[FakeExecuteResult(scalar_value=_daemon(ip="10.42.3.227"))]
    )
    body = training_daemons.DaemonHeartbeat(name="nornir-a", host="humpy")

    daemon = await training_daemons.heartbeat(body, session, None)

    assert session.commits == 1
    assert daemon.ip_address == "10.42.3.227"
