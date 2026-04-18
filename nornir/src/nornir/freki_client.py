"""
freki_client.py — thin async HTTP client for Freki's ML endpoints.

Every Nornir interaction with the backend goes through here so that retries,
timeouts, and error translation live in a single place. The client raises
``FrekiError`` on non-2xx responses with enough context for the caller to
decide whether to keep running.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

ML_CONTROL_SECRET_HEADER = "X-Grimnir-ML-Control-Secret"
MODEL_UPLOAD_SECRET_HEADER = "X-Grimnir-Model-Upload-Secret"


class FrekiError(RuntimeError):
    """Raised when a Freki HTTP call returns a non-2xx status."""

    def __init__(self, method: str, url: str, status: int, body: str) -> None:
        super().__init__(f"{method} {url} → {status}: {body[:200]}")
        self.status = status
        self.body = body


class FrekiClient:
    """Async HTTP wrapper around Freki's training/model endpoints."""

    def __init__(
        self,
        base_url: str,
        timeout_s: float = 30.0,
        ml_control_shared_secret: str | None = None,
        model_upload_shared_secret: str | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
        )
        self._ml_control_shared_secret = ml_control_shared_secret or None
        self._model_upload_shared_secret = model_upload_shared_secret or None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> FrekiClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    # ── internal helpers ──────────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        expected: tuple[int, ...] = (200, 201, 204),
    ) -> httpx.Response:
        response = await self._client.request(
            method,
            path,
            json=json_body,
            params=params,
            data=data,
            files=files,
            headers=headers,
        )
        if response.status_code not in expected:
            raise FrekiError(method, path, response.status_code, response.text)
        return response

    # ── daemon lifecycle ──────────────────────────────────────────────────────

    def _ml_control_headers(self) -> dict[str, str] | None:
        if not self._ml_control_shared_secret:
            return None
        return {
            ML_CONTROL_SECRET_HEADER: self._ml_control_shared_secret,
        }

    async def heartbeat_daemon(
        self,
        name: str,
        host: str,
        ip_address: str | None,
        capabilities: dict[str, Any],
    ) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "/api/training-daemons/heartbeat",
            json_body={
                "name": name,
                "host": host,
                "ip_address": ip_address,
                "capabilities": capabilities,
            },
            headers=self._ml_control_headers(),
        )
        return response.json()

    # ── jobs ──────────────────────────────────────────────────────────────────

    async def list_queued_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        response = await self._request(
            "GET",
            "/api/training-jobs",
            params={"status": "queued", "limit": limit},
        )
        return response.json()

    async def claim_job(self, job_id: int, daemon_id: int) -> dict[str, Any] | None:
        """Returns the claimed job on success, or None if someone else won."""
        try:
            response = await self._request(
                "POST",
                f"/api/training-jobs/{job_id}/claim",
                json_body={"daemon_id": daemon_id},
                headers=self._ml_control_headers(),
            )
        except FrekiError as exc:
            if exc.status == 409:
                return None
            raise
        return response.json()

    async def heartbeat_job(self, job_id: int, daemon_id: int, claim_token: str) -> None:
        await self._request(
            "POST",
            f"/api/training-jobs/{job_id}/heartbeat",
            json_body={"daemon_id": daemon_id, "claim_token": claim_token},
            headers=self._ml_control_headers(),
        )

    async def complete_job(self, job_id: int, daemon_id: int, claim_token: str) -> None:
        await self._request(
            "POST",
            f"/api/training-jobs/{job_id}/complete",
            json_body={"daemon_id": daemon_id, "claim_token": claim_token},
            headers=self._ml_control_headers(),
        )

    async def fail_job(self, job_id: int, daemon_id: int, claim_token: str, error: str) -> None:
        await self._request(
            "POST",
            f"/api/training-jobs/{job_id}/fail",
            json_body={
                "daemon_id": daemon_id,
                "claim_token": claim_token,
                "error": error[:2000],
            },
            headers=self._ml_control_headers(),
        )

    # ── training data (cursor-paginated) ──────────────────────────────────────

    async def iter_training_data(
        self,
        *,
        time_start: str,
        time_end: str,
        rooms: list[str],
        page_size: int = 2000,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield training sample rows page-by-page until the cursor exhausts."""
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {
                "time_start": time_start,
                "time_end": time_end,
                "rooms": ",".join(rooms),
                "page_size": page_size,
            }
            if cursor is not None:
                params["cursor"] = cursor
            response = await self._request("GET", "/api/training-data", params=params)
            page = response.json()
            for row in page["rows"]:
                yield row
            cursor = page.get("next_cursor")
            if cursor is None:
                return

    # ── model upload ──────────────────────────────────────────────────────────

    async def upload_model(
        self,
        *,
        name: str,
        model_bytes: bytes,
        metrics: dict[str, Any],
        feature_config: dict[str, Any],
        training_job_id: int | None,
    ) -> dict[str, Any]:
        form: dict[str, Any] = {
            "name": name,
            "metrics": json.dumps(metrics),
            "feature_config": json.dumps(feature_config),
        }
        if training_job_id is not None:
            form["training_job_id"] = str(training_job_id)
        headers = None
        if self._model_upload_shared_secret:
            headers = {
                MODEL_UPLOAD_SECRET_HEADER: self._model_upload_shared_secret,
            }
        response = await self._request(
            "POST",
            "/api/models",
            data=form,
            files={"model_data": (f"{name}.joblib", model_bytes, "application/octet-stream")},
            headers=headers,
            expected=(201,),
        )
        return response.json()
