"""hardware.py — Detect available GPU and CPU capabilities."""

from __future__ import annotations

import subprocess

import psutil


def detect() -> dict:
    """Return a capabilities dict describing available hardware."""
    return {"gpu": _detect_gpu(), "cpu": _detect_cpu()}


def _detect_gpu() -> list[dict]:
    """Query nvidia-smi for GPU name and VRAM. Returns empty list if unavailable."""
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            timeout=5,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        gpus = []
        for line in output.strip().splitlines():
            parts = line.split(",", 1)
            if len(parts) == 2:
                gpus.append({"name": parts[0].strip(), "vram_mb": int(parts[1].strip())})
        return gpus
    except Exception:
        return []


def _detect_cpu() -> dict:
    try:
        freq = psutil.cpu_freq()
        return {
            "cores": psutil.cpu_count(logical=False) or 1,
            "threads": psutil.cpu_count(logical=True) or 1,
            "freq_mhz": round(freq.max) if freq else None,
        }
    except Exception:
        return {"cores": 1, "threads": 1, "freq_mhz": None}
