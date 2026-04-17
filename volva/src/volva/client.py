"""client.py — Freki API client for Völva."""

from __future__ import annotations

from typing import Any

import httpx


class FrekiClient:
    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")
        self._http = httpx.AsyncClient(base_url=self._base, timeout=30.0)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_active_model_metadata(self) -> dict | None:
        """Return the active model's metadata dict, or None if none is active."""
        resp = await self._http.get("/api/models")
        resp.raise_for_status()
        models = resp.json()
        for m in models:
            if m.get("is_active"):
                return m
        return None

    async def download_model_bytes(self, model_id: int) -> bytes:
        resp = await self._http.get(f"/api/models/{model_id}/data", timeout=60.0)
        resp.raise_for_status()
        return resp.content

    async def push_predictions(self, payload: dict[str, Any]) -> None:
        resp = await self._http.put("/api/predictions/current", json=payload)
        resp.raise_for_status()

    async def stream_csi(self):
        """Yield parsed SSE payloads from GET /api/stream."""
        async with self._http.stream("GET", "/api/stream", timeout=None) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    import json
                    try:
                        yield json.loads(line[6:])
                    except Exception:
                        continue
