from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import FakeExecuteResult, FakeSession
from csi_models import TrainingJob
from fastapi import HTTPException
from freki.routers import training_jobs
from sqlalchemy.dialects import postgresql


def _job_spec() -> training_jobs.JobSpec:
    return training_jobs.JobSpec(
        time_start=datetime(2026, 4, 18, 19, 0, tzinfo=UTC),
        time_end=datetime(2026, 4, 18, 20, 0, tzinfo=UTC),
        rooms=["living_room"],
    )


def _running_job(
    *,
    status: str = "running",
    claim_token: str = "claim-token-123456",
    daemon_id: int = 7,
) -> TrainingJob:
    return TrainingJob(
        id=11,
        status=status,
        spec={"rooms": ["living_room"]},
        daemon_id=daemon_id,
        claim_token=claim_token,
        created_at=datetime(2026, 4, 18, 19, 0, tzinfo=UTC),
        claimed_at=datetime(2026, 4, 18, 19, 5, tzinfo=UTC),
        heartbeat_at=datetime(2026, 4, 18, 19, 6, tzinfo=UTC),
        completed_at=None,
        error=None,
    )


@pytest.mark.asyncio
async def test_create_job_rejects_unknown_rooms() -> None:
    session = FakeSession(execute_results=[FakeExecuteResult(all_rows=[("living_room",)])])
    body = training_jobs.JobCreate(
        spec=_job_spec().model_copy(update={"rooms": ["living_room", "garage"]})
    )

    with pytest.raises(HTTPException, match="Unknown room"):
        await training_jobs.create_job(body, session)


@pytest.mark.asyncio
async def test_create_job_persists_valid_job() -> None:
    session = FakeSession(execute_results=[FakeExecuteResult(all_rows=[("living_room",)])])
    body = training_jobs.JobCreate(spec=_job_spec())

    job = await training_jobs.create_job(body, session)

    assert session.commits == 1
    assert session.refreshes == 1
    assert session.added == [job]
    assert job.spec["rooms"] == ["living_room"]
    assert job.daemon_id is None


@pytest.mark.asyncio
async def test_claim_job_requires_known_daemon() -> None:
    session = FakeSession(scalar_results=[None])

    with pytest.raises(HTTPException, match="Unknown daemon_id"):
        await training_jobs.claim_job(11, training_jobs.ClaimBody(daemon_id=7), session)


@pytest.mark.asyncio
async def test_claim_job_assigns_claim_token_and_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_token = "fixed-claim-token"
    claimed = _running_job(claim_token=expected_token)
    session = FakeSession(
        scalar_results=[7],
        execute_results=[FakeExecuteResult(scalar_value=claimed)],
    )
    monkeypatch.setattr(training_jobs.secrets, "token_urlsafe", lambda _n: expected_token)

    job = await training_jobs.claim_job(11, training_jobs.ClaimBody(daemon_id=7), session)

    assert session.commits == 1
    assert job.claim_token == expected_token
    statement, _, _ = session.execute_calls[0]
    params = statement.compile(dialect=postgresql.dialect()).params
    assert expected_token in params.values()
    assert 7 in params.values()


@pytest.mark.asyncio
async def test_heartbeat_job_rejects_wrong_daemon_or_token() -> None:
    session = FakeSession(execute_results=[FakeExecuteResult(scalar_value=None)])
    body = training_jobs.JobControlBody(daemon_id=7, claim_token="wrong-token-123456")

    with pytest.raises(HTTPException, match="Job is not running for this daemon"):
        await training_jobs.heartbeat_job(11, body, session)

    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_complete_job_commits_owned_job() -> None:
    completed = _running_job(status="complete", claim_token=None)
    session = FakeSession(execute_results=[FakeExecuteResult(scalar_value=completed)])
    body = training_jobs.JobControlBody(daemon_id=7, claim_token="claim-token-123456")

    job = await training_jobs.complete_job(11, body, session)

    assert session.commits == 1
    assert job.status == "complete"
    assert job.claim_token is None


@pytest.mark.asyncio
async def test_fail_job_rejects_wrong_daemon_or_token() -> None:
    session = FakeSession(execute_results=[FakeExecuteResult(scalar_value=None)])
    body = training_jobs.FailBody(
        daemon_id=7,
        claim_token="wrong-token-123456",
        error="boom",
    )

    with pytest.raises(HTTPException, match="Job is not running for this daemon"):
        await training_jobs.fail_job(11, body, session)

    assert session.rollbacks == 1
