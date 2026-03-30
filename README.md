# CLAUDE.md — CSI Localization Subsystem (Grimnir project)

This document is a handoff brief for Claude Code. It describes a new subsystem
to be integrated into the Grimnir monorepo. Read this fully before touching any
files.

---

## What this is

A Wi-Fi CSI (Channel State Information) based human presence detection and
room-level localization system. ESP32-S3 devices capture CSI from Wi-Fi frames
and stream binary UDP packets to a containerized aggregator, which writes to
PostgreSQL + TimescaleDB. A FastAPI backend serves a live web dashboard with
real-time visualization and a training data labeling UI.

This is the **data collection and visualization layer**. The ML training
pipeline (consuming labeled data from Postgres) is out of scope here and will
be built separately on the P100/M4 GPU machines.

---

## Monorepo placement

The Grimnir repo uses raven-themed component names (Huginn = transmitter,
Muninn = receivers). Suggested integration layout:

```
grimnir/
├── huginn/                  ← rename from firmware/transmitter/
├── muninn/                  ← rename from firmware/receiver/
├── firmware/
│   └── config.h             ← shared firmware config, stays at this path
├── csi-aggregator/          ← rename from aggregator/
├── csi-backend/             ← rename from backend/
├── csi-frontend/            ← rename from frontend/
├── db/
│   └── 001_schema.sql       ← can merge with existing db migrations if any
├── compose/
│   ├── compose.yaml
│   └── .env.example
├── helm/
│   └── csi/                 ← helm chart, merge with existing helm/ if present
└── ansible/
    └── deploy.yaml          ← merge with existing ansible playbooks if present
```

If the repo already has a `helm/`, `ansible/`, or `db/` directory, merge into
those rather than creating duplicates. Check for conflicts before merging.

---

## Hardware context

- **3× ESP32-S3** devices (expandable to 6, schema and code already support this)
  - 1 transmitter (Huginn): sends UDP broadcast beacons at 10 Hz on a fixed channel
  - 2 receivers (Muninn): capture CSI, stream binary UDP to aggregator
- **No Pi Zero W** — ESP32s send UDP directly to the aggregator container
- **Postgres on dedicated NAS** (Debian/Ubuntu), with TimescaleDB extension
- **GPU machines** (Tesla M4, P100) connect directly to Postgres for ML training
- **k8s cluster** or standalone Docker for running the aggregator and backend

---

## Component inventory

### `firmware/config.h`
Shared config header included by both transmitter and receiver firmware.
Must be edited before flashing:
- `WIFI_SSID` / `WIFI_PASSWORD`
- `AGGREGATOR_HOST` — DNS hostname resolving to the aggregator container
- `CSI_WIFI_CHANNEL` — dedicate a clean 2.4 GHz channel (1, 6, or 11)
- `RECEIVER_NAME` — set uniquely per receiver board before each flash

### `firmware/transmitter/` (→ huginn/)
ESP-IDF v5.1+ project. Connects to Wi-Fi, broadcasts UDP frames at
`TX_BEACON_INTERVAL_MS` (default 100ms / 10 Hz). Receivers extract CSI from
these frames at the 802.11 PHY layer. Payload content is irrelevant.

Build:
```bash
cd huginn
idf.py set-target esp32s3
idf.py build flash monitor
```

### `firmware/receiver/` (→ muninn/)
ESP-IDF v5.1+ project. Captures CSI via `esp_wifi_set_csi_rx_cb`, serializes
to a binary UDP packet, sends to `AGGREGATOR_HOST:AGGREGATOR_PORT` (default
5005). Uses DNS resolution at boot — requires `AGGREGATOR_HOST` to resolve
before the first packet is sent (retries 10× with 2s delay then reboots).

**UDP packet format** (little-endian, defined in `parser.py` and `main.c`):
```
[0..3]   magic uint32     = 0x43534921 ("CSI!")
[4..5]   version uint16   = 1
[6..21]  receiver_name char[16]
[22..27] transmitter_mac uint8[6]
[28..29] rssi int16 (dBm)
[30..31] noise_floor int16 (dBm)
[32..33] channel uint16
[34..35] bandwidth_mhz uint16
[36..37] antenna_count uint16
[38..39] subcarrier_count uint16
[40..43] timestamp_us uint32 (device uptime micros, wraps ~71min)
[44..N]  amplitude float32[]  len = antenna_count * subcarrier_count
[N..M]   phase float32[]      len = antenna_count * subcarrier_count
```

Build (repeat with different `RECEIVER_NAME` per board):
```bash
cd muninn
# edit ../../firmware/config.h: set RECEIVER_NAME="rx_ground"
idf.py set-target esp32s3
idf.py build flash monitor
```

### `aggregator/` (→ csi-aggregator/)
Python 3.12 asyncio service. Listens on UDP 5005, parses packets, batches
inserts into TimescaleDB. Auto-registers new receiver boards in the DB on first
contact — no manual seeding needed for new devices.

Key config (all env vars):
- `DATABASE_URL` — asyncpg DSN, required
- `UDP_PORT` — default 5005
- `BATCH_SIZE` — default 50 rows
- `BATCH_TIMEOUT_MS` — default 500ms

New receivers self-register via upsert on `receivers.name`. The
`receiver_heartbeats` table is updated on every packet for "last seen" tracking.

### `backend/` (→ csi-backend/)
Python 3.12 FastAPI service. Three router modules:

| Router | Prefix | Purpose |
|--------|--------|---------|
| `stream.py` | `GET /api/stream` | SSE, pushes per-receiver summary every 1s |
| `history.py` | `GET /api/history/variance` | Per-minute variance from continuous aggregate |
| `history.py` | `GET /api/history/snapshot` | Raw amplitude arrays for heatmap |
| `history.py` | `GET /api/history/receivers` | Receiver list with heartbeat status |
| `labels.py` | `GET/POST/DELETE /api/labels` | Training label CRUD + backfill |

The backend also serves `frontend/index.html` as a static file from `/`.
In production, put nginx in front and serve the HTML directly.

Key config:
- `DATABASE_URL` — asyncpg DSN, required
- `PORT` — default 8000

### `frontend/index.html`
Single-file vanilla JS + Chart.js dashboard. Mobile-first responsive layout
with bottom tab nav on phones, multi-column grid on desktop. PWA-ready
(`apple-mobile-web-app-capable`, `theme-color`, `viewport-fit=cover`).

Four sections:
1. **Live** — receiver cards with RSSI, sample count, variance bar
2. **Chart** — 60-minute amplitude variance timeline per receiver
3. **Map** — subcarrier amplitude heatmap (latest frame, per-receiver)
4. **Label** — training data annotation UI (tag the last N minutes as a room)

The `API` constant at the top of the script is `''` (same-origin). Change to
`'http://host:8000'` for local dev with a separate backend process.

### `db/001_schema.sql`
Run once against your Postgres instance after installing TimescaleDB:

```bash
psql -U postgres -c "CREATE DATABASE csi;"
psql -U postgres -c "CREATE USER csi_user WITH PASSWORD 'changeme'; GRANT ALL ON DATABASE csi TO csi_user;"
psql -U postgres -d csi -f db/001_schema.sql
```

Creates:
- `receivers` — one row per ESP32 board
- `csi_samples` — TimescaleDB hypertable, 7-day chunks, compressed after 7 days
- `labels` — annotated time ranges for training data
- `receiver_heartbeats` — last-seen per receiver
- `csi_variance_1min` — continuous aggregate (materialized, auto-refreshes every 1min)

The `receivers` table is seeded with 3 placeholder rows with dummy MACs
(`00:00:00:00:00:0{1,2,3}`). Update the MACs after flashing — they're logged
to serial on boot. Or just let the aggregator upsert the real MACs when the
first packet arrives.

### `compose/compose.yaml`
Standalone deployment. Requires `.env` with `DATABASE_URL`.

```bash
cd compose
cp .env.example .env   # edit DATABASE_URL
docker compose up -d
```

Exposes UDP 5005 (aggregator) and TCP 8000 (backend + frontend).

### `helm/csi/`
Helm chart for k8s deployment. Key values to override:
- `image.aggregator.repository` / `image.backend.repository` — your registry
- `database.url` — the Postgres DSN (stored as a k8s Secret)
- `service.aggregatorType` — `LoadBalancer` (MetalLB) or `NodePort`
- `ingress.host` — your internal domain, e.g. `csi.home.arpa`

The aggregator Service needs a stable IP reachable from the ESP32s. If using
MetalLB, pin the IP with the annotation in `helm/csi/templates/all.yaml`.

### `ansible/deploy.yaml`
Ansible playbook that builds both images, pushes to registry, and deploys the
Helm chart. Requires `kubernetes.core` and `community.docker` collections.

```bash
pip install ansible kubernetes
ansible-galaxy collection install kubernetes.core community.docker

ansible-playbook ansible/deploy.yaml \
  -e db_url="postgresql://csi_user:pass@nas-host:5432/csi" \
  -e registry="your-registry.example.com" \
  -e aggregator_lb_ip="192.168.1.50"
```

---

## Integration checklist for Claude Code

- [ ] Decide on directory naming (keep as-is or apply Grimnir raven naming)
- [ ] Merge `db/001_schema.sql` with any existing migration system in the repo
- [ ] Merge `compose/compose.yaml` with existing compose files if present
- [ ] Merge `helm/csi/` with existing helm directory if present
- [ ] Merge `ansible/deploy.yaml` with existing playbooks if present
- [ ] Update `firmware/config.h` with real SSID, password, and aggregator hostname
- [ ] Update `receivers` seed rows in schema with real MAC addresses (or skip — aggregator auto-registers)
- [ ] Set `DATABASE_URL` in `.env` / k8s Secret / Ansible vars
- [ ] Ensure TimescaleDB extension is installed on the Postgres server
- [ ] Add `csi-aggregator.home.arpa` (or chosen hostname) to local DNS pointing at aggregator IP
- [ ] Confirm UDP port 5005 is reachable from the ESP32 VLAN to the aggregator

---

## Known gaps / future work

- **ML pipeline** — not included. The labeled `csi_samples` rows (where
  `label IS NOT NULL`) are the training data. Connect GPU machines directly
  to Postgres and query from there.
- **Phase calibration** — raw phase data is hardware-offset-contaminated.
  Current code stores raw phase; amplitude is reliable and sufficient for
  presence detection. Phase sanitization (e.g. conjugate multiplication across
  antennas) should be added as a preprocessing step before ML training.
- **Multi-person detection** — current architecture captures data for it but
  the ML problem is significantly harder than single-person. Defer until single-
  person localization is working.
- **Transmitter redundancy** — only 1 transmitter currently. For robustness,
  any receiver can be promoted to transmitter by flashing the transmitter
  firmware. The schema supports mixed roles.
- **OTA firmware updates** — not implemented. Currently requires physical
  flash via USB.
- **HTTPS / auth on backend** — currently no authentication. Put behind a
  reverse proxy (nginx + basic auth or your existing auth layer) before
  exposing beyond localhost.
