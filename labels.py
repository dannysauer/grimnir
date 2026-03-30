[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "csi-backend"
version = "0.1.0"
description = "FastAPI backend — SSE streaming + REST API for CSI data"
requires-python = ">=3.12"
dependencies = [
    "fastapi==0.115.5",
    "uvicorn[standard]==0.32.1",
    "asyncpg==0.29.0",
    "structlog==24.4.0",
    "python-dotenv==1.0.1",
]

[project.scripts]
csi-backend = "csi_backend.main:run"

[tool.hatch.build.targets.wheel]
packages = ["src/csi_backend"]
