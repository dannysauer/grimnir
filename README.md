# Grimnir

> **Work in progress** — the data collection, training, and live inference
> pipeline is functional; auth, tests, and deployment polish are still in
> progress.

Wi-Fi Channel State Information (CSI) based human presence detection and room-level localization for a multi-floor home. Named after Odin's epithet *Grimnir* — "the Hooded One" — an observer who sees without being seen.

ESP32-S3 devices capture CSI from 802.11 frames and stream the data to a
containerized backend that writes to PostgreSQL/TimescaleDB. A live web
dashboard provides receiver status, amplitude variance charts, subcarrier
heatmaps, and a labeling UI for building ML training data. The ML pipeline is
implemented end-to-end: Nornir trains models from labeled samples, Völva runs
live inference, and Freki serves the active prediction state to Home Assistant
and the dashboard.

---

## Components

The project uses Norse names for each component, following the raven/wolf theme from Odin's mythology. See [GRIMNIR.md](GRIMNIR.md) for the full naming reference.

| Component | Directory | Role |
|-----------|-----------|------|
| **Huginn** | `firmware/huginn/` | ESP32-S3 transmitter firmware — broadcasts beacon frames at 10 Hz on a fixed Wi-Fi channel for CSI capture |
| **Muninn** | `firmware/muninn/` | ESP32-S3 receiver firmware — captures CSI from incoming 802.11 frames and streams binary UDP packets to Geri |
| **Geri** | `geri/` | Aggregator service — receives UDP CSI packets from Muninn devices and batch-writes them to TimescaleDB |
| **Freki** | `freki/` | Backend API — FastAPI service providing REST endpoints and Server-Sent Events for live receiver status and historical data |
| **Nornir** | `nornir/` | Training daemon — claims queued training jobs from Freki, fits sklearn models, and uploads trained artifacts back to the backend |
| **Völva** | `volva/` | Inference service — loads the active model, consumes live CSI, and publishes current room predictions back to Freki |
| **Hlidskjalf** | `hlidskjalf/` | Web dashboard — single-file vanilla JS frontend for live CSI visualization, variance charts, subcarrier heatmaps, and ML training data labeling |
| **Mimir** | `mimir/` | Database layer — TimescaleDB schema, SQLAlchemy ORM models, async engine helpers, and first-boot SQL bootstrap |
| **Bifrost** | `bifrost/` | Deployment infrastructure — Docker Compose for standalone deployment, Helm chart for Kubernetes, and Ansible playbook for automated rollout |

---

## Hardware

- **1× ESP32-S3** running Huginn — broadcasts UDP beacon frames
- **2× ESP32-S3** running Muninn — capture CSI and stream to Geri (expandable to 5 receivers without schema changes)
- **PostgreSQL + TimescaleDB** on a dedicated home server (not containerized)
- Kubernetes cluster for running Geri, Freki, Nornir, and Völva
- GPU machines (Tesla P100) available if future model trainers need them

---

## Quick Start

### Development Tooling

If you use `asdf`, install the repo-pinned toolchain first:

```bash
asdf install
```

This repo currently pins:
- Python `3.12.7` for the Python services and local test/lint runs
- Node.js `24.14.1` for repo-local JS tooling if needed later
- Helm `3.16.2` for chart linting and packaging

### Database

Install TimescaleDB on your PostgreSQL server.

If the database in `DATABASE_URL` already exists, Grimnir now bootstraps the
schema automatically on first service start. `mimir/001_schema.sql` remains the
authoritative SQL reference and can still be applied manually if needed.

If the database does not exist and the configured user has `CREATEDB`, the
startup bootstrap will create it automatically before applying the schema.

Important:
- The target database must either already have the `timescaledb` extension
  installed, or the configured database role must be allowed to run
  `CREATE EXTENSION timescaledb`
- On PostgreSQL 12 / TimescaleDB 2.11, that typically means a superuser role
  for fully automatic first boot on a fresh database

Manual bootstrap reference:

```bash
psql -U postgres -c "CREATE DATABASE csi;"
psql -U postgres -c "CREATE USER csi_user WITH PASSWORD 'changeme' CREATEDB;"
psql -U postgres -c "ALTER USER csi_user WITH SUPERUSER;"
psql -U postgres -c "GRANT ALL ON DATABASE csi TO csi_user;"
psql -U postgres -d csi -f mimir/001_schema.sql
```

### Docker Compose (standalone)

```bash
cp .env.example .env
# Edit .env — set DATABASE_URL to point at your PostgreSQL instance
docker compose -f bifrost/compose.yaml up -d
```

This starts the full shipped application stack: Geri, Freki, Nornir, and
Völva. PostgreSQL/TimescaleDB is still external and must be reachable via
`DATABASE_URL`.

Optional hardening:
- Set `MODEL_UPLOAD_SHARED_SECRET` in `.env` to require the
  `X-Grimnir-Model-Upload-Secret` header on `POST /api/models`.
- Use the same value for both Freki and Nornir so the training daemon can keep
  uploading models normally.
- Set `ML_CONTROL_SHARED_SECRET` in `.env` to require the
  `X-Grimnir-ML-Control-Secret` header on Nornir's daemon heartbeats plus job
  claim/heartbeat/complete/fail calls.

### Kubernetes (Helm)

```bash
helm install grimnir oci://ghcr.io/dannysauer/charts/grimnir \
  --set database.url="postgresql+asyncpg://csi_user:changeme@db.example.com:5432/csi" \
  --set geri.service.type=LoadBalancer
```

The chart deploys the same full application pipeline: Geri, Freki, Nornir, and
Völva.

Optional hardening:
- Set `modelUploadAuth.sharedSecret` or point `modelUploadAuth.existingSecret`
  at a Secret containing `MODEL_UPLOAD_SHARED_SECRET` to gate model uploads.
- Set `mlControlAuth.sharedSecret` or point `mlControlAuth.existingSecret` at
  a Secret containing `ML_CONTROL_SHARED_SECRET` to gate Nornir's ML control
  writes.

### Firmware

Edit `firmware/config.h` with your Wi-Fi credentials, aggregator hostname, and receiver name, then flash with ESP-IDF v5.1+:

```bash
cd firmware/huginn   # or muninn
idf.py set-target esp32s3
idf.py build flash monitor
```

---

## Status

| Component | Status |
|-----------|--------|
| Huginn firmware | ✅ Written |
| Muninn firmware | ✅ Written |
| Geri aggregator | ✅ Written |
| Freki backend | ✅ Written |
| Nornir training daemon | ✅ Written |
| Völva inference service | ✅ Written |
| Hlidskjalf dashboard | ✅ Written |
| Mimir (DB models + bootstrap migrations) | ✅ Written |
| ML training pipeline | ✅ Implemented |
