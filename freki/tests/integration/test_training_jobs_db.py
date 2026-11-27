"""Training-job queue routes against a real database."""

from __future__ import annotations

import asyncio

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def _register_daemon(client: httpx.AsyncClient, name: str) -> int:
    response = await client.post(
        "/api/training-daemons/heartbeat", json={"name": name, "host": name}
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _queue_job(client: httpx.AsyncClient, engine: AsyncEngine) -> int:
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO rooms (name, floor) VALUES ('kitchen', 0) ON CONFLICT DO NOTHING")
        )
    response = await client.post(
        "/api/training-jobs",
        json={
            "spec": {
                "model_type": "random_forest",
                "time_start": "2026-11-01T00:00:00Z",
                "time_end": "2026-11-01T01:00:00Z",
                "rooms": ["kitchen"],
            }
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# Verifies GRM-020: concurrent claims hand a queued job to exactly one daemon.
# Twenty simultaneous claims make a race in the claim logic show up on nearly
# every run; a single run is strong evidence, not proof.
async def test_concurrent_claims_have_one_winner(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    claimants = 20
    daemons = [await _register_daemon(client, f"nornir-{i}") for i in range(claimants)]
    job_id = await _queue_job(client, engine)

    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(
                client.post(f"/api/training-jobs/{job_id}/claim", json={"daemon_id": daemon_id})
            )
            for daemon_id in daemons
        ]
    responses = [task.result() for task in tasks]

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [200] + [409] * (claimants - 1)
    winner = next(r.json() for r in responses if r.status_code == 200)
    assert winner["status"] == "running"
    assert winner["claim_token"]

    async with engine.connect() as conn:
        stored = (
            await conn.execute(
                text("SELECT daemon_id, claim_token FROM training_jobs WHERE id = :id"),
                {"id": job_id},
            )
        ).one()
    assert stored == (winner["daemon_id"], winner["claim_token"])


# Verifies GRM-032: only the claiming daemon's id and token can update the job.
async def test_job_updates_require_the_claim(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    owner = await _register_daemon(client, "nornir-owner")
    other = await _register_daemon(client, "nornir-other")
    job_id = await _queue_job(client, engine)
    claim = await client.post(f"/api/training-jobs/{job_id}/claim", json={"daemon_id": owner})
    assert claim.status_code == 200, claim.text
    token = claim.json()["claim_token"]

    wrong_token = {"daemon_id": owner, "claim_token": "not-the-claim-token"}
    wrong_daemon = {"daemon_id": other, "claim_token": token}
    for body in (wrong_token, wrong_daemon):
        for action in ("heartbeat", "complete"):
            response = await client.post(f"/api/training-jobs/{job_id}/{action}", json=body)
            assert response.status_code == 409, (action, body, response.text)
        response = await client.post(
            f"/api/training-jobs/{job_id}/fail", json={**body, "error": "nope"}
        )
        assert response.status_code == 409, ("fail", body, response.text)

    response = await client.post(
        f"/api/training-jobs/{job_id}/heartbeat", json={"daemon_id": owner, "claim_token": token}
    )
    assert response.status_code == 200, response.text
    response = await client.post(
        f"/api/training-jobs/{job_id}/complete", json={"daemon_id": owner, "claim_token": token}
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "complete"
