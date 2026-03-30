# Grimnir — Claude Code Context

## Project Overview

Grimnir is a Wi-Fi CSI (Channel State Information) based human presence detection
and room-level localization system for a multi-floor home. Named after Odin's
epithet "the Hooded One" — an observer who sees without being seen.

ESP32-S3 devices capture CSI from 802.11 frames and stream binary UDP packets to
a containerized aggregator, which writes to PostgreSQL + TimescaleDB. A FastAPI
backend serves a mobile-first web dashboard with live receiver status, variance
charts, subcarrier amplitude heatmaps, and a labeling tool for building ML
training data.

## Norse Naming Convention

See `GRIMNIR.md` for the full naming reference. Summary:

| Component | Norse Name | Role |
|-----------|-----------|------|
| Transmitter firmware | **Huginn** | ESP32-S3 that broadcasts beacon frames |
| Receiver firmware | **Muninn** | ESP32-S3(s) that capture CSI + stream UDP |
| Aggregator service | **Geri** (`geri/`) | UDP → TimescaleDB writer |
| Backend API | **Freki** (`freki/`) | FastAPI REST + SSE |
| Frontend | **Hlidskjalf** (`hlidskjalf/`) | Web dashboard |
| Database/models | **Mimir** (`mimir/`) | SQLAlchemy + Alembic (not yet implemented) |
| Deployment | **Bifrost** (`bifrost/`) | Compose, Helm, Ansible |

## Hardware

- **1× ESP32-S3** transmitter (Huginn) — broadcasts UDP beacons at 10 Hz
- **2× ESP32-S3** receivers (Muninn) — capture CSI, stream to aggregator
- Expandable to 6 total devices (1 tx + 5 rx) without schema changes
- **humpy** — Ubuntu 20.04 NAS/server running PostgreSQL 12 + TimescaleDB 2.11.2
- Kubernetes cluster available for container workloads
- GPU machines (Tesla M4, P100) available for ML training

## Repository Structure

```
grimnir/
├── CLAUDE.md
├── GRIMNIR.md                      # Naming reference (see this for full Norse map)
├── .env.example                    # Environment variable template
├── mimir/
│   └── 001_schema.sql              # Database schema — run once to set up TimescaleDB
├── geri/                           # UDP → TimescaleDB writer
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── src/geri/
│       ├── main.py                 # UDP listener + batch writer + startup sequence
│       ├── parser.py               # Binary CSI packet parser (mirrors firmware format)
│       └── db.py                   # SQLAlchemy insert helpers
├── freki/                          # FastAPI REST + SSE
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── src/freki/
│       ├── main.py                 # FastAPI app + startup sequence
│       ├── db.py                   # SessionDep FastAPI dependency
│       └── routers/
│           ├── stream.py           # GET /api/stream  (SSE, 1s updates)
│           ├── history.py          # GET /api/history/variance|snapshot|receivers
│           └── labels.py           # CRUD /api/labels
├── hlidskjalf/
│   └── index.html                  # Single-file mobile-first dashboard (vanilla JS)
├── firmware/
│   ├── config.h                    # ← EDIT BEFORE FLASHING each board
│   ├── huginn/main/main.c          # Transmitter ESP-IDF v5.1+ C firmware
│   └── muninn/main/main.c          # Receiver ESP-IDF v5.1+ C firmware
└── bifrost/                        # Deployment: Compose + Helm + Ansible
    ├── compose.yaml
    ├── helm/
    └── ansible/deploy.yaml
```

## Technology Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Firmware | C, ESP-IDF v5.1+ | ESP32-S3 target |
| Transport | UDP binary packets | Custom wire format, see below |
| Aggregator | Python 3.12, asyncio | SQLAlchemy async + asyncpg |
| Database | PostgreSQL 12 + TimescaleDB 2.11.2 | On humpy (not containerised) |
| ORM / Migrations | SQLAlchemy 2.0, Alembic | models package shared by all services |
| Backend | FastAPI, uvicorn | SSE + REST |
| Frontend | Vanilla JS, Chart.js 4, date-fns adapter | Single HTML file |
| Containers | Docker, Docker Compose | Build context is repo root |
| Kubernetes | Helm chart + Ansible playbook | Uses external DB on humpy |

## Python Conventions

- Python 3.12+
- All new code uses `pyproject.toml` with `hatchling` build backend
- Dependencies pinned to specific versions
- `asyncio` throughout; asyncpg driver at runtime, psycopg2-binary only for Alembic migrations
- `structlog` for logging in all services
- Type hints everywhere; `from __future__ import annotations` at top of each file

## Database

**Server:** humpy (Ubuntu 20.04), PostgreSQL 12, TimescaleDB 2.11.2
**Database name:** `csi`
**User:** `csi_user`

### Schema Overview

| Table/View | Type | Purpose |
|-----------|------|---------|
| `receivers` | table | One row per ESP32-S3 device |
| `csi_samples` | hypertable | Raw CSI — one row per UDP packet, partitioned by time (7-day chunks) |
| `labels` | table | Human-annotated time windows for ML training |
| `receiver_heartbeats` | table | Last-seen per receiver (upserted by Geri) |
| `csi_variance_1min` | continuous aggregate | Per-minute RSSI avg + amplitude variance, auto-refreshed |

**TimescaleDB specifics:**
- `csi_samples` is a hypertable (7-day chunks)
- Compression after 7 days (`compress_segmentby = 'receiver_id'`)
- Retention: drop raw chunks after 90 days
- Continuous aggregate `csi_variance_1min` refreshes every minute

**Schema management:** ORM models in `mimir/`, migrations via Alembic. Both services
run `run_migrations(DATABASE_URL)` at startup (idempotent). `mimir/001_schema.sql`
is a plain-SQL reference of the same schema, useful for bootstrapping or inspection.

To bootstrap a fresh database manually:
```bash
psql -U postgres -c "CREATE DATABASE csi;"
psql -U postgres -c "CREATE USER csi_user WITH PASSWORD 'changeme'; GRANT ALL ON DATABASE csi TO csi_user;"
psql -U postgres -d csi -f mimir/001_schema.sql
```
Or just start a service with `DATABASE_URL` set — Alembic will apply migrations automatically.

## UDP Wire Protocol

The binary packet format is defined in `firmware/muninn/main/main.c` and parsed
in `geri/src/geri/parser.py`. They must stay in sync.

```
Offset  Size  Type        Field
------  ----  ----------  -----
 0       4    uint32      magic = 0x43534921 ("CSI!")
 4       2    uint16      version = 1
 6      16    char[16]    receiver_name (null-padded ASCII)
22       6    uint8[6]    transmitter MAC bytes
28       2    int16       rssi (dBm)
30       2    int16       noise_floor (dBm)
32       2    uint16      channel
34       2    uint16      bandwidth_mhz
36       2    uint16      antenna_count
38       2    uint16      subcarrier_count
40       4    uint32      timestamp_us (device uptime, wraps ~71 min)
44       N    float32[]   amplitude  (N = antenna_count × subcarrier_count)
44+N     N    float32[]   phase      (N = antenna_count × subcarrier_count)
```
All little-endian. Header is exactly 44 bytes (`_Static_assert` in firmware confirms this).

## Startup Sequence (both aggregator and backend)

1. Call `run_migrations(DATABASE_URL)` — Alembic upgrades to head (idempotent)
2. Call `init_engine(DATABASE_URL)` — creates SQLAlchemy async engine + session factory
3. Start service (UDP listener / uvicorn)

Migrations use psycopg2 (sync). Runtime uses asyncpg. `migrate.py` handles URL
conversion automatically (`postgresql+asyncpg://` → `postgresql+psycopg2://`).

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/stream` | SSE — JSON snapshot every 1s, all receivers |
| GET | `/api/history/receivers` | All receivers with heartbeat |
| GET | `/api/history/variance?receiver_id=&minutes=` | Per-minute RSSI variance (uses continuous aggregate, falls back to raw) |
| GET | `/api/history/snapshot?receiver_id=&limit=` | Raw CSI samples for heatmap |
| GET | `/api/labels?minutes=` | Recent labels |
| POST | `/api/labels` | Create label + backfill `csi_samples.label` |
| DELETE | `/api/labels/{id}` | Delete label + clear backfill |
| GET | `/health` | Liveness check |

## Docker Build Notes

Build context for both Dockerfiles is the **repo root** (not the service subdirectory).
This is because both services depend on the `mimir/` package which sits at the root.

```dockerfile
# In geri/Dockerfile and freki/Dockerfile:
COPY mimir/ /mimir
RUN pip install --no-cache-dir /mimir
```

In `bifrost/compose.yaml` the build context is `..` (repo root). When building manually:
```bash
docker build -f geri/Dockerfile -t grimnir/geri .
docker build -f freki/Dockerfile -t grimnir/freki .
```

## Deployment

### Standalone (Docker Compose)

The compose file uses the external database on humpy — it does NOT spin up a
Postgres container. Set `DATABASE_URL` in `.env` to point at humpy.

```bash
cp .env.example .env
# edit .env
docker compose -f bifrost/compose.yaml up -d
```

### Kubernetes

```bash
ansible-playbook bifrost/ansible/deploy.yaml \
  -e db_url="postgresql+asyncpg://csi_user:changeme@humpy.home.arpa:5432/csi" \
  -e registry="your-registry.example.com" \
  -e aggregator_lb_ip="192.168.1.50"
```

The geri Service should be type LoadBalancer so ESP32s can reach it by
stable LAN IP. Set a DNS A record `geri.home.arpa` (or `csi-aggregator.home.arpa`)
pointing at that IP.

## Firmware

- ESP-IDF v5.1+, target `esp32s3`
- Edit `firmware/config.h` before each flash:
  - `WIFI_SSID` / `WIFI_PASSWORD`
  - `AGGREGATOR_HOST` — DNS name of aggregator (resolved via DHCP-provided DNS)
  - `RECEIVER_NAME` — unique per board (e.g. `"rx_ground"`, `"rx_upstairs"`)
- Recommended installer: IDF Installation Manager GUI (`eim-gui-windows-x64.msi`)
- Flash: `idf.py set-target esp32s3 && idf.py build flash monitor`
- New receivers auto-register in the DB on first packet — no manual setup needed

## Known TODOs / Areas for Claude Code to Address

- [ ] **Mimir package not yet implemented** — `geri` and `freki` both import
      `from csi_models import ...` but `mimir/` only has `001_schema.sql` so far;
      the SQLAlchemy models, engine factory, and Alembic migrations need to be written
      before either service can run
- [ ] `hlidskjalf` has no error state for failed SSE connections beyond the dot colour
- [ ] No tests exist yet — pytest + pytest-asyncio for geri/freki,
      coverage of `geri/src/geri/parser.py` is highest priority
- [ ] Helm values `aggregatorLoadBalancerIP` is passed as empty string when not
      set — Helm template should use `if` guard to omit the field entirely rather
      than setting it to `""`
- [ ] Phase calibration — raw phase data is hardware-offset-contaminated; amplitude
      is reliable for presence detection. Phase sanitization should be added as a
      preprocessing step before ML training.
- [ ] HTTPS / auth on freki — no authentication currently. Put behind nginx +
      basic auth before exposing beyond localhost.

## ML Pipeline (Future)

Training data is collected via the Label tab in the dashboard. The `csi_samples`
table has a `label` column (nullable) that gets backfilled when a label is created.

Query training data:
```sql
SELECT time, receiver_id, amplitude, phase, label
FROM csi_samples
WHERE label IS NOT NULL
ORDER BY time;
```

GPU machines (Tesla P100 recommended) are available for training. No ML code
exists yet — this is the next major phase after the data collection pipeline
is validated.
