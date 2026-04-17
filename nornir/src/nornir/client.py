"""client.py — HTTP client for the Freki API."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx


class FrekiClient:
    def __init__(self, base_url: str, daemon_name: str) -> None:
        self._base = base_url.rstrip("/")
        self._daemon_name = daemon_name
        self._http = httpx.AsyncClient(base_url=self._base, timeout=30.0)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def heartbeat(self, host: str, capabilities: dict) -> dict:
        resp = await self._http.post(
            "/api/training-daemons/heartbeat",
            json={"name": self._daemon_name, "host": host, "capabilities": capabilities},
        )
        resp.raise_for_status()
        return resp.json()

    async def poll_queued_job(self) -> dict | None:
        resp = await self._http.get("/api/training-jobs", params={"status": "queued"})
        resp.raise_for_status()
        jobs = resp.json()
        return jobs[0] if jobs else None

    async def claim_job(self, job_id: int) -> dict:
        resp = await self._http.post(
            f"/api/training-jobs/{job_id}/claim",
            json={"daemon_name": self._daemon_name},
        )
        resp.raise_for_status()
        return resp.json()

    async def job_heartbeat(self, job_id: int) -> None:
        resp = await self._http.post(f"/api/training-jobs/{job_id}/heartbeat")
        resp.raise_for_status()

    async def complete_job(self, job_id: int) -> None:
        resp = await self._http.post(f"/api/training-jobs/{job_id}/complete")
        resp.raise_for_status()

    async def fail_job(self, job_id: int, error: str) -> None:
        resp = await self._http.post(
            f"/api/training-jobs/{job_id}/fail",
            json={"error": error},
        )
        resp.raise_for_status()

    async def upload_model(
        self,
        name: str,
        model_bytes: bytes,
        metrics: dict,
        feature_config: dict,
        training_job_id: int,
    ) -> dict:
        files = {"file": ("model.joblib", model_bytes, "application/octet-stream")}
        data = {
            "name": name,
            "training_job_id": str(training_job_id),
            "metrics": json.dumps(metrics),
            "feature_config": json.dumps(feature_config),
        }
        resp = await self._http.post("/api/models", files=files, data=data, timeout=120.0)
        resp.raise_for_status()
        return resp.json()

    async def stream_training_data(
        self,
        time_start: str,
        time_end: str,
        rooms: list[str] | None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        params: dict[str, str] = {"time_start": time_start, "time_end": time_end}
        if rooms:
            params["rooms"] = ",".join(rooms)
        async with self._http.stream("GET", "/api/training-data", params=params) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.strip():
                    yield json.loads(line)

    async def upload_model_with_retry(
        self,
        name: str,
        model_bytes: bytes,
        metrics: dict,
        feature_config: dict,
        training_job_id: int,
        max_attempts: int = 10,
    ) -> dict:
        delay = 2.0
        for attempt in range(1, max_attempts + 1):
            try:
                return await self.upload_model(
                    name, model_bytes, metrics, feature_config, training_job_id
                )
            except Exception as exc:
                if attempt == max_attempts:
                    raise
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60.0)
        raise RuntimeError("unreachable")
