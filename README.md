# Grimnir

> **Work in progress** — data collection and visualization pipeline is functional; ML training pipeline is not yet built.

Wi-Fi Channel State Information (CSI) based human presence detection and room-level localization for a multi-floor home. Named after Odin's epithet *Grimnir* — "the Hooded One" — an observer who sees without being seen.

ESP32-S3 devices capture CSI from 802.11 frames and stream the data to a containerized backend that writes to PostgreSQL/TimescaleDB. A live web dashboard provides receiver status, amplitude variance charts, subcarrier heatmaps, and a labeling UI for building ML training data.

---

## Components

The project uses Norse names for each component, following the raven/wolf theme from Odin's mythology. See [GRIMNIR.md](GRIMNIR.md) for the full naming reference.

| Component | Directory | Role |
|-----------|-----------|------|
| **Huginn** | `firmware/huginn/` | ESP32-S3 transmitter firmware — broadcasts beacon frames at 10 Hz on a fixed Wi-Fi channel for CSI capture |
| **Muninn** | `firmware/muninn/` | ESP32-S3 receiver firmware — captures CSI from incoming 802.11 frames and streams binary UDP packets to Geri |
| **Geri** | `geri/` | Aggregator service — receives UDP CSI packets from Muninn devices and batch-writes them to TimescaleDB |
| **Freki** | `freki/` | Backend API — FastAPI service providing REST endpoints and Server-Sent Events for live receiver status and historical data |
| **Hlidskjalf** | `hlidskjalf/` | Web dashboard — single-file vanilla JS frontend for live CSI visualization, variance charts, subcarrier heatmaps, and ML training data labeling |
| **Mimir** | `mimir/` | Database layer — TimescaleDB schema, SQLAlchemy ORM models, and Alembic migrations *(not yet implemented — next milestone)* |
| **Bifrost** | `bifrost/` | Deployment infrastructure — Docker Compose for standalone deployment, Helm chart for Kubernetes, and Ansible playbook for automated rollout |

---

## Hardware

- **1× ESP32-S3** running Huginn — broadcasts UDP beacon frames
- **2× ESP32-S3** running Muninn — capture CSI and stream to Geri (expandable to 5 receivers without schema changes)
- **PostgreSQL + TimescaleDB** on a dedicated home server (not containerized)
- Kubernetes cluster for running Geri and Freki
- GPU machines (Tesla P100) available for future ML training

---

## Quick Start

### Database

Install TimescaleDB on your PostgreSQL server, then run the schema:

```bash
psql -U postgres -c "CREATE DATABASE csi;"
psql -U postgres -c "CREATE USER csi_user WITH PASSWORD 'changeme'; GRANT ALL ON DATABASE csi TO csi_user;"
psql -U postgres -d csi -f mimir/001_schema.sql
```

### Docker Compose (standalone)

```bash
cp .env.example .env
# Edit .env — set DATABASE_URL to point at your PostgreSQL instance
docker compose -f bifrost/compose.yaml up -d
```

### Kubernetes (Helm)

```bash
helm install grimnir oci://ghcr.io/dannysauer/charts/grimnir \
  --set database.url="postgresql+asyncpg://csi_user:changeme@humpy.home.arpa:5432/csi" \
  --set geri.service.type=LoadBalancer
```

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
| Geri aggregator | ✅ Written — blocked on Mimir |
| Freki backend | ✅ Written — blocked on Mimir |
| Hlidskjalf dashboard | ✅ Written |
| Mimir (DB models + migrations) | 🚧 Not yet implemented |
| ML training pipeline | 📋 Planned |
