[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "csi-aggregator"
version = "0.1.0"
description = "UDP CSI packet receiver → PostgreSQL/TimescaleDB writer"
requires-python = ">=3.12"
dependencies = [
    "asyncpg==0.29.0",
    "structlog==24.4.0",
]

[project.scripts]
csi-aggregator = "csi_aggregator.main:run"

[tool.hatch.build.targets.wheel]
packages = ["src/csi_aggregator"]
