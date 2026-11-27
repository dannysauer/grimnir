"""Model registry routes against a real database."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from freki.routers import models
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def _insert_models(engine: AsyncEngine, *names: str) -> list[int]:
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                INSERT INTO trained_models (name, model_data, metrics, feature_config)
                SELECT name, '\\x00'::bytea, '{}'::jsonb, '{"version": 1}'::jsonb
                  FROM unnest(CAST(:names AS text[])) AS name
                RETURNING id
                """
            ),
            {"names": list(names)},
        )
        return [row[0] for row in result]


async def _active_ids(engine: AsyncEngine) -> list[int]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id FROM trained_models WHERE is_active ORDER BY id")
        )
        return [row[0] for row in result]


# Verifies GRM-014: activating a second model leaves exactly one active.
async def test_activate_switches_the_active_model(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    first, second = await _insert_models(engine, "first", "second")

    response = await client.post(f"/api/models/{first}/activate")
    assert response.status_code == 200
    assert response.json()["is_active"] is True

    response = await client.post(f"/api/models/{second}/activate")
    assert response.status_code == 200, response.text
    assert response.json()["id"] == second

    assert await _active_ids(engine) == [second]


# Verifies GRM-014.
async def test_activate_the_active_model_again_is_a_no_op(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    (model_id,) = await _insert_models(engine, "only")

    for _ in range(2):
        response = await client.post(f"/api/models/{model_id}/activate")
        assert response.status_code == 200, response.text

    assert await _active_ids(engine) == [model_id]


# Verifies GRM-014: concurrent activations still leave exactly one active.
async def test_concurrent_activations_leave_one_active(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    ids = await _insert_models(engine, "a", "b", "c", "d")

    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(client.post(f"/api/models/{model_id}/activate")) for model_id in ids
        ]
    responses = [task.result() for task in tasks]

    assert [r.status_code for r in responses] == [200] * len(ids)
    assert len(await _active_ids(engine)) == 1


async def test_activate_unknown_model_returns_404(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await _insert_models(engine, "present")

    response = await client.post("/api/models/9999/activate")

    assert response.status_code == 404
    assert await _active_ids(engine) == []


async def test_list_and_active_report_size(client: httpx.AsyncClient, engine: AsyncEngine) -> None:
    (model_id,) = await _insert_models(engine, "sized")
    response = await client.post(f"/api/models/{model_id}/activate")
    assert response.status_code == 200, response.text

    listed = await client.get("/api/models")
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["size_bytes"] == 1

    active = await client.get("/api/models/active")
    assert active.status_code == 200, active.text
    assert active.json()["size_bytes"] == 1


async def test_upload_returns_the_stored_model(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    response = await client.post(
        "/api/models",
        data={
            "name": "uploaded",
            "metrics": '{"accuracy": 0.5}',
            "feature_config": '{"version": 1}',
        },
        files={"model_data": ("model.joblib", b"\x01\x02\x03", "application/octet-stream")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "uploaded"
    assert body["size_bytes"] == 3
    assert body["is_active"] is False


async def test_activation_times_out_with_503_when_the_lock_is_held(
    client: httpx.AsyncClient, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    (model_id,) = await _insert_models(engine, "blocked")
    monkeypatch.setattr(models, "ACTIVATION_LOCK_TIMEOUT", "100ms")

    async with engine.connect() as holder:
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": models.MODEL_ACTIVATION_LOCK_ID}
        )
        response = await client.post(f"/api/models/{model_id}/activate")
        await holder.rollback()

    assert response.status_code == 503, response.text
    assert await _active_ids(engine) == []
