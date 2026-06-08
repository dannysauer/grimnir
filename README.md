# Grimnir

Grimnir is a Wi-Fi Channel State Information (CSI) presence detection and
room-level localization system for a multi-floor home.

ESP32-S3 devices capture CSI from 802.11 frames and stream binary UDP packets
to a containerized backend. The backend writes to PostgreSQL with TimescaleDB,
serves a web dashboard, records labels for model training, trains room
classifiers, and publishes current room predictions for consumers such as Home
Assistant.

The project is a personal monorepo. Backstage and TechDocs are not part of the
distribution model; GitHub-rendered Markdown is the primary documentation
surface.

## Documentation Map

Start here, then follow the component docs for the task you are doing:

| Task | Doc |
|------|-----|
| Understand the monorepo layout, component roles, and command matrix | [Monorepo guide](docs/monorepo.md) |
| Build, flash, and verify ESP32-S3 firmware | [Firmware build and flash guide](docs/firmware-build-and-flash.md) |
| Read the Freki REST/SSE API and service health endpoints | [API reference](docs/api-reference.md) |
| Read the Muninn-to-Geri UDP packet contract | [UDP wire protocol](docs/udp-wire-protocol.md) |
| Run the stack with Compose, Helm, or Ansible | [Deployment guide](docs/deployment.md) |
| Install or configure the Helm chart directly | [Helm chart README](bifrost/helm/grimnir/README.md) |
| Understand the component names | [Naming reference](GRIMNIR.md) |
| Track known follow-up work | [TODO checklist](TODO.md) |

`CLAUDE.md` is agent context for code assistants. It should agree with these
reader-facing docs, but it is not the only source of documentation.

## Components

| Component | Path | Role | Primary docs |
|-----------|------|------|--------------|
| Huginn | `firmware/huginn/` | ESP32-S3 transmitter firmware. Broadcasts beacon frames at 10 Hz on the configured Wi-Fi channel. | [Firmware guide](docs/firmware-build-and-flash.md) |
| Muninn | `firmware/muninn/` | ESP32-S3 receiver firmware. Captures CSI from Huginn frames and sends binary UDP packets to Geri. | [Firmware guide](docs/firmware-build-and-flash.md), [UDP protocol](docs/udp-wire-protocol.md) |
| Geri | `geri/` | UDP aggregator. Receives Muninn packets, sends ACKs, records receiver heartbeats, and batch-writes CSI rows to TimescaleDB. | [Monorepo guide](docs/monorepo.md), [UDP protocol](docs/udp-wire-protocol.md) |
| Freki | `freki/` | FastAPI backend. Serves the dashboard, REST API, SSE streams, model endpoints, and Prometheus metrics. | [API reference](docs/api-reference.md), [Deployment guide](docs/deployment.md) |
| Nornir | `nornir/` | Training daemon. Claims queued training jobs from Freki, trains scikit-learn models, uploads artifacts, and reports job status. | [API reference](docs/api-reference.md), [Monorepo guide](docs/monorepo.md) |
| Volva | `volva/` | Live inference service. Consumes Freki's CSI SSE stream, loads the active model, and publishes current room predictions. | [API reference](docs/api-reference.md), [Monorepo guide](docs/monorepo.md) |
| Hlidskjalf | `hlidskjalf/` | Single-file web dashboard for receiver status, charts, labeling, training jobs, and model management. | [API reference](docs/api-reference.md) |
| Mimir | `mimir/` | Shared database package. Provides SQLAlchemy models, first-boot SQL migrations, and feature extraction helpers. | [Monorepo guide](docs/monorepo.md) |
| Bifrost | `bifrost/` | Deployment assets for Docker Compose, Helm, and Ansible. | [Deployment guide](docs/deployment.md) |

## Hardware

- 1 ESP32-S3 running Huginn as the transmitter.
- 2 or more ESP32-S3 boards running Muninn as receivers.
- PostgreSQL with TimescaleDB on a reachable server. The shipped Compose and
  Helm deployments expect the database to be external.
- Docker Compose for standalone deployment, or a Kubernetes cluster for the
  Helm deployment.

## Quick Start

Install the repo-pinned tools if you use `asdf`:

```bash
asdf install
```

The pinned toolchain includes Python 3.12.7, Node.js 24.14.1, Helm 3.16.2,
and pre-commit 4.5.1.

Create a database or point Grimnir at an existing PostgreSQL database with the
TimescaleDB extension available. The runtime URL must use the asyncpg driver:

```bash
postgresql+asyncpg://csi_user@db.example.com:5432/csi
```

The example omits a password. Put the real credential-bearing URL in `.env` for
Compose, or in a Kubernetes Secret for Helm.

For a standalone Compose run:

```bash
cp .env.example .env
# Edit .env and set DATABASE_URL.
docker compose -f bifrost/compose.yaml up -d
```

For Helm:

```bash
CHART_VERSION=0.1.1
helm install grimnir oci://ghcr.io/dannysauer/charts/grimnir \
  --version "$CHART_VERSION" \
  --set database.url="postgresql+asyncpg://csi_user@db.example.com:5432/csi"
```

For firmware:

```bash
cd firmware/muninn
idf.py set-target esp32s3
idf.py build flash monitor
```

See the [deployment guide](docs/deployment.md) and
[firmware guide](docs/firmware-build-and-flash.md) for prerequisites,
verification, and operational notes.

## Current Status

The data collection, dashboard, labeling, training, and live inference pipeline
is implemented and usable for a home deployment. The main open work is tracked
in [TODO.md](TODO.md), including broader Freki authentication, supply-chain
hardening, and phase calibration for ML quality.
