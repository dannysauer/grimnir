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
| Trainer daemon | **Nornir** (`nornir/`) | Claims training jobs, fits sklearn models |
| Inference service | **Völva** (`volva/`) | Consumes `/api/csi-stream`, publishes room predictions |
| Frontend | **Hlidskjalf** (`hlidskjalf/`) | Web dashboard |
| Database/models | **Mimir** (`mimir/`) | SQLAlchemy models + first-boot SQL bootstrap |
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
├── TODO.md                         # Checklist cross-referencing GitHub issues
├── .env.example                    # Environment variable template
├── .pre-commit-config.yaml         # pre-commit hook configuration
├── pyproject.toml                  # Root ruff/tool config (not a package)
├── renovate.json5                  # Renovate dependency update config (SHA-pinned)
├── .claude/
│   ├── settings.json               # Claude Code hooks (runs pre-commit before commits)
│   └── hooks/
│       └── pre-commit-check.sh     # PreToolUse hook script
├── docs/
│   ├── firmware-build-and-flash.md # Linux + Windows firmware build guide
│   └── style-guides/
│       └── google/                 # Google style guides (git subtree, gh-pages branch)
│           ├── pyguide.md          # Python style guide
│           ├── shellguide.md       # Shell style guide
│           └── ...                 # cppguide.html, jsguide.html, etc.
├── mimir/
│   ├── pyproject.toml
│   ├── 001_schema.sql              # SQL reference for the schema/bootstrap
│   └── src/csi_models/
│       ├── __init__.py             # Public exports for shared DB helpers/models
│       ├── engine.py               # Async engine + session factory initialisation
│       ├── migrate.py              # Idempotent first-boot SQL bootstrap runner
│       ├── models.py               # Shared SQLAlchemy ORM models
│       └── sql/001_schema.sql      # Bundled bootstrap SQL for installed package
├── geri/                           # UDP → TimescaleDB writer
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── src/geri/
│       ├── main.py                 # UDP listener + batch writer + startup sequence
│       ├── parser.py               # Binary CSI packet parser (mirrors firmware format)
│       ├── db.py                   # SQLAlchemy insert helpers
│       └── metrics.py              # Prometheus metrics definitions
├── freki/                          # FastAPI REST + SSE
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── src/freki/
│       ├── main.py                 # FastAPI app + startup sequence
│       ├── db.py                   # SessionDep FastAPI dependency
│       ├── metrics.py              # Prometheus metrics definitions
│       ├── orphan_reaper.py        # Lifespan task: fail orphaned training jobs
│       └── routers/
│           ├── stream.py           # GET /api/stream       (SSE, 1s summary)
│           ├── csi_stream.py       # GET /api/csi-stream   (SSE, raw CSI rows)
│           ├── history.py          # GET /api/history/variance|snapshot|receivers
│           ├── labels.py           # CRUD /api/labels
│           ├── training_daemons.py # Nornir daemon registration + heartbeats
│           ├── training_jobs.py    # Training-job queue (create/claim/report)
│           ├── training_data.py    # Cursor-paginated training-data export
│           ├── models.py           # Trained-model upload/list/activate/download
│           ├── rooms.py            # Room CRUD for labels and predictions
│           └── predictions.py      # GET/PUT current predictions + SSE stream
├── nornir/                         # ML trainer daemon (claims jobs, fits sklearn)
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── src/nornir/
│       ├── main.py                 # Claim loop, metrics server, signal handling
│       ├── freki_client.py         # Typed async HTTP client for Freki
│       ├── train.py                # Feature-window collection + RandomForest fit
│       └── metrics.py              # Prometheus metrics on :8001
├── volva/                          # Live inference service (SSE → predictions)
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── src/volva/
│       ├── main.py                 # FastAPI app with /health + /metrics
│       ├── model_loader.py         # Active-model fetch + hot-swap + version check
│       ├── predict.py              # SSE consumer, per-receiver windowing, publish
│       └── metrics.py              # Prometheus metrics (volva_* namespace)
├── hlidskjalf/
│   └── index.html                  # Single-file mobile-first dashboard (vanilla JS)
├── firmware/
│   ├── config.h                    # ← EDIT BEFORE FLASHING each board
│   ├── huginn/
│   │   ├── platformio.ini          # PlatformIO build (framework = espidf)
│   │   └── main/main.c             # Transmitter ESP-IDF v5.1+ C firmware
│   └── muninn/
│       ├── platformio.ini          # PlatformIO build (framework = espidf)
│       └── main/main.c             # Receiver ESP-IDF v5.1+ C firmware
└── bifrost/                        # Deployment: Compose + Helm + Ansible
    ├── compose.yaml
    ├── helm/grimnir/               # Helm chart (both geri + freki)
    │   ├── Chart.yaml
    │   ├── values.yaml             # All options documented inline
    │   ├── files/
    │   │   └── grimnir-dashboard.json  # Grafana dashboard (Helm .Files.Get)
    │   └── templates/              # Kubernetes manifests
    └── ansible/deploy.yaml         # Ansible → Helm deploy with MetalLB/external-dns
```

## Technology Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Firmware | C, ESP-IDF v5.1+ | ESP32-S3 target; build locally (see `docs/firmware-build-and-flash.md`) |
| Transport | UDP binary packets | Custom wire format, see below |
| Aggregator | Python 3.12, asyncio | SQLAlchemy async + asyncpg; prometheus-client for metrics |
| Database | PostgreSQL 12 + TimescaleDB 2.11.2 | External server (not containerised) |
| ORM / Migrations | SQLAlchemy 2.0, bundled SQL bootstrap | shared `csi_models` package used by all services |
| Backend | FastAPI, uvicorn | SSE + REST; prometheus-fastapi-instrumentator for metrics |
| Frontend | Vanilla JS, Chart.js 4, date-fns adapter | Single HTML file |
| Containers | Docker, Docker Compose | Build context is repo root |
| Kubernetes | Helm chart + Ansible playbook | Uses external DB; MetalLB + external-dns optional |
| ML | scikit-learn 1.5.2, numpy 2.1.3, joblib | RandomForestClassifier; features in shared `csi_models.features` |
| Observability | prometheus-client, prometheus-fastapi-instrumentator | Geri `:8001`; Freki `:8000/metrics`; Nornir `:8001`; Völva `:8002/metrics` |
| Helm extras | VPA, ServiceMonitor, Grafana sidecar ConfigMap | All disabled by default; enable via values |

## Python Conventions

- Python 3.12+
- Repo-local tool versions are pinned in `.tool-versions` for `asdf`
  (`python 3.12.7`, `nodejs 24.14.1`, `helm 3.16.2`)
- All new code uses `pyproject.toml` with `hatchling` build backend
- Dependencies pinned to specific versions
- `asyncio` throughout; asyncpg driver at runtime, psycopg2-binary for sync bootstrap/migration work
- `structlog` for logging in all services — **always JSON** (see Logging Requirements below)
- Type hints everywhere; `from __future__ import annotations` at top of each file

## Logging Requirements

**All services MUST emit structured JSON logs via structlog.** Use this exact
configuration in every service `main.py`:

```python
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, LOG_LEVEL, logging.INFO)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)
```

Use `log.info("event.name", key=value)` — event names use dot notation
(e.g. `"db.batch_inserted"`, `"aggregator.starting"`). Never use f-strings
in log messages; pass data as keyword arguments.

uvicorn access logs are disabled (`access_log=False`) — request metrics are
handled by Prometheus instead.

## Documentation Requirements

When adding new capabilities, environment variables, dependencies, configuration
options, API endpoints, or breaking changes, **always** update:

1. **Reader-facing docs in `docs/`** — update the relevant API, deployment,
   firmware, protocol, and monorepo pages first
2. **`CLAUDE.md`** — keep agent context aligned with the reader-facing docs
   and current source
3. **`TODO.md`** — check off completed items; add new follow-up items with
   GitHub issue numbers where relevant
4. **`README.md`** — if the change is user-visible (new quick-start step,
   new component, changed endpoint, etc.)
5. **`pyproject.toml`** — add any new runtime dependencies with pinned versions
6. **GitHub issues** — create or update the tracking issue / epic for the work,
   and close completed issues after the changes land on `main`

These updates are not optional — they ensure continuity across agent sessions.

## Work Tracking Requirements

- Substantial work starts with a tracking issue. If the work is broad enough to
  split cleanly, open a parent epic and use sub-issues.
- Keep `TODO.md` aligned with the issue tracker for repo-level work.
- Reference issue numbers in follow-up notes and close completed issues once the
  implementation is merged or pushed to `main`.

## GitHub Actions Requirements

- Every third-party GitHub Action in workflow `uses:` entries must be pinned to
  a full upstream release tag such as `actions/checkout@v6.0.2`.
- Never use floating major tags like `@v4` or `@v6` in committed workflows.
- Before changing an action version, verify the current tag from the upstream
  action repository release page or API.
- The repo pre-commit config enforces this rule; keep that check passing rather
  than bypassing it.

## Code Style

This project uses the **Google style guides** for all languages. The guides are
vendored as a git subtree at `docs/style-guides/google/` and are always
available without a network connection.

| Language | Guide |
|----------|-------|
| Python | `docs/style-guides/google/pyguide.md` |
| Shell | `docs/style-guides/google/shellguide.md` |
| C (firmware) | `docs/style-guides/google/cppguide.html` (C++ guide; apply C-compatible rules) |
| HTML/CSS | `docs/style-guides/google/htmlcssguide.html` |
| JavaScript | `docs/style-guides/google/jsguide.html` |

Key Python rules from the Google guide that apply here:
- 4-space indentation (enforced by ruff-format)
- `"""Docstrings."""` for all public functions/classes
- Type annotations on all function signatures
- `from __future__ import annotations` at the top of every file
- No mutable default arguments
- Prefer `with` statements for resource management

To update the style guides to the latest version:
```bash
git subtree pull --prefix=docs/style-guides/google \
  https://github.com/google/styleguide.git gh-pages --squash
```

## Commit Messages

**All commits must use Conventional Commits format.** The release workflow
(`release.yml`) parses commit messages to calculate the next semver version and
decide whether to cut a release — a commit that doesn't match will silently skip
the release.

Format: `<type>(<scope>): <description>`

| Type | When to use | Version bump |
|------|-------------|--------------|
| `feat` | New user-visible feature | minor |
| `fix` | Bug fix | patch |
| `chore` | Maintenance, deps, tooling | patch |
| `docs` | Documentation only | patch |
| `refactor` | Refactor with no behaviour change | patch |
| `perf` | Performance improvement | patch |
| `test` | Adding or fixing tests | patch |
| `ci` | CI/CD changes only | patch |

- `BREAKING CHANGE:` in the commit body triggers a major bump.
- Scope is optional but encouraged (e.g. `feat(hlidskjalf):`, `fix(freki):`).
- A commit with no matching type (e.g. `hlidskjalf: …`) will **not** trigger a
  release — always use one of the types above.

Examples:
```
feat(hlidskjalf): auto-discover probes from database on load
fix(freki): remove raw SQL INTERVAL clause in list_labels
chore(deps): bump pre-commit hooks to latest
```

## Pre-Commit

All commits **must** pass pre-commit checks. The hooks run automatically via
the `.claude/settings.json` PreToolUse hook — do not use `--no-verify` unless
explicitly instructed.

To install pre-commit locally:
```bash
asdf install
pip install pre-commit
pre-commit install        # installs the git hook
pre-commit run --all-files  # run manually against all files
```

Hooks configured in `.pre-commit-config.yaml`:
- **trailing-whitespace**, **end-of-file-fixer**, **check-yaml**, **check-json**,
  **check-merge-conflict** — general hygiene
- **ruff** — Python linting with auto-fix (E, F, I/isort, W, UP, B rules)
- **ruff-format** — Python formatting (black-compatible, 100-char lines)
- **shellcheck** — shell script linting (warning severity)
- **actionlint** — GitHub Actions workflow linting (including inline shell)

pre-commit.ci runs on every PR and auto-pushes fixes. Chart templates
(`bifrost/helm/grimnir/templates/`) are excluded from YAML checking because
Helm's `{{ }}` syntax is not valid YAML.

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

**Schema management:** ORM models and bootstrap logic live in `mimir/`. Both services
run `run_migrations(DATABASE_URL)` at startup (idempotent). `mimir/001_schema.sql`
is the plain-SQL reference of the same schema, and `mimir/src/csi_models/sql/001_schema.sql`
is bundled into the installed package for first-boot bootstrap.

**Privilege requirement for fully automatic first boot:** the target database
must either already have the `timescaledb` extension installed, or the
configured role must be able to run `CREATE EXTENSION timescaledb`. On
PostgreSQL 12 / TimescaleDB 2.11 that typically means a superuser role.

To bootstrap a fresh database manually:
```bash
psql -U postgres -c "CREATE DATABASE csi;"
psql -U postgres -c "CREATE USER csi_user WITH PASSWORD 'changeme' CREATEDB;"
psql -U postgres -c "ALTER USER csi_user WITH SUPERUSER;"
psql -U postgres -c "GRANT ALL ON DATABASE csi TO csi_user;"
psql -U postgres -d csi -f mimir/001_schema.sql
```
Or just start a service with `DATABASE_URL` set — the bundled SQL bootstrap will
create the schema automatically if the role has the required privileges.

## UDP Wire Protocol

The current Muninn packet format is version 2 with a 60-byte header and a
32-byte receiver name. Geri still accepts version 1 for backward compatibility.

Reader-facing contract: `docs/udp-wire-protocol.md`.

Source of truth:
- Current firmware layout: `firmware/muninn/main/main.c`
- Parser constants and validation: `geri/src/geri/parser.py`
- Regression tests: `geri/tests/test_parser.py`

## Startup Sequence (both aggregator and backend)

1. Call `run_migrations(DATABASE_URL)` — bundled SQL bootstrap runs pending migrations (idempotent)
2. Call `init_engine(DATABASE_URL)` — creates SQLAlchemy async engine + session factory
3. Start service (UDP listener / uvicorn)

Bootstrap uses psycopg2 (sync). Runtime uses asyncpg. `migrate.py` handles URL
conversion automatically (`postgresql+asyncpg://` → `postgresql+psycopg2://`).

## API Endpoints

Reader-facing contract: `docs/api-reference.md`.

Freki also exposes FastAPI-generated docs at `/openapi.json`, `/docs`, and
`/redoc` when the service is running.

High-level surface:
- Service: `GET /health`, `GET /metrics`
- Streams/history: `GET /api/stream`, `GET /api/csi-stream`,
  `GET /api/history/receivers`, `GET /api/history/variance`,
  `GET /api/history/snapshot`
- Rooms and labels: `GET/POST /api/rooms`, `PATCH/DELETE /api/rooms/{room}`,
  `GET/POST /api/labels`, `DELETE /api/labels/{id}`
- Training: `GET /api/training-data`, `GET /api/training-daemons`,
  `POST /api/training-daemons/heartbeat`, `GET/POST /api/training-jobs`,
  `POST /api/training-jobs/{id}/claim`, `heartbeat`, `complete`, `fail`, and
  `cancel`
- Models: `GET/POST /api/models`, `GET /api/models/active`,
  `GET /api/models/{id}/data`, `POST /api/models/{id}/activate`
- Predictions: `GET/PUT /api/predictions/current`,
  `GET /api/predictions/stream`

## Docker Build Notes

Build context for service Dockerfiles is the **repo root** (not the service
subdirectory). This is because service packages depend on the `mimir/` package.

```dockerfile
# In service Dockerfiles:
COPY mimir/ /mimir
RUN pip install --no-cache-dir /mimir
```

In `bifrost/compose.yaml` the build context is `..` (repo root). When building
manually:

```bash
docker build -f geri/Dockerfile -t grimnir/geri .
docker build -f freki/Dockerfile -t grimnir/freki .
docker build -f nornir/Dockerfile -t grimnir/nornir .
docker build -f volva/Dockerfile -t grimnir/volva .
```

## Deployment

Reader-facing deployment contract: `docs/deployment.md`.

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

The geri Service should be type LoadBalancer. Use MetalLB address pool annotations
and external-dns `hostname` annotation to get an IP from the pool and create DNS
automatically — no static IP configuration required:

```yaml
geri:
  service:
    annotations:
      metallb.universe.tf/address-pool: default
      external-dns.alpha.kubernetes.io/hostname: csi-aggregator.home.example.com
```

## Firmware

See `docs/firmware-build-and-flash.md` for full Linux and Windows build instructions.

- ESP-IDF v5.1+, target `esp32s3`; firmware is built locally (credentials embedded)
- **Two build systems supported** — use whichever you have installed:
  - **ESP-IDF CLI** (`idf.py build flash monitor`) — see Linux/Windows sections in the guide
  - **PlatformIO CLI** (`pio run -t upload`) — uses `firmware/{huginn,muninn}/platformio.ini`;
    must use `framework = espidf` (CSI APIs are not available in the Arduino framework)
- Copy `firmware/config.local.h.example` to `firmware/config.local.h` before
  flashing each board. `config.local.h` is gitignored and overrides
  `firmware/config.h` defaults:
  - `WIFI_SSID` / `WIFI_PASSWORD`
  - `AGGREGATOR_HOST` — DNS name of aggregator (resolved via DHCP-provided DNS)
  - `RECEIVER_NAME` — unique per board (e.g. `"rx_ground"`, `"rx_upstairs"`)
  - `HUGINN_MAC` — transmitter MAC accepted by Muninn
- New receivers auto-register in the DB on first packet — no manual setup needed

## Observability

Geri exposes Prometheus metrics on `METRICS_PORT` (default `8001`):
- `geri_packets_received_total{receiver_name}` — ingestion counter
- `geri_packets_invalid_total` — parse failure counter
- `geri_packets_dropped_total` — queue-full drop counter
- `geri_batch_writes_total{status}` — DB write counter
- `geri_batch_write_duration_seconds` — DB write latency histogram
- `geri_batch_size_rows` — rows-per-batch histogram

Freki exposes metrics via `prometheus-fastapi-instrumentator` at `GET /metrics`:
- `http_request_duration_seconds{handler,method,status}` — request latency histogram
- `freki_sse_connections_active` — live SSE connection gauge

Helm chart supports optional `ServiceMonitor` resources and a Grafana sidecar
`ConfigMap` — enable via `prometheus.serviceMonitor.enabled` and
`grafana.dashboard.enabled`.

## Known TODOs / Areas for Claude Code to Address

See `TODO.md` for the full checklist with GitHub issue numbers. Key items:

- [ ] **Tests** (#4) — pytest + pytest-asyncio; `parser.py` is highest priority
- [ ] **HTTPS / auth** (#5) — no authentication on freki; add nginx + basic auth. Narrow mitigations: `POST /api/models` can be gated with `MODEL_UPLOAD_SHARED_SECRET` (#29), and Nornir's daemon/job ML control writes can be gated with `ML_CONTROL_SHARED_SECRET` (#27).
- [ ] **Phase calibration** (#7) — raw phase has hardware offsets; preprocess before ML

## ML Pipeline

Training and inference run as two separate services:

- **Nornir** (`nornir/`) — a claim-loop daemon. Registers with Freki, claims
  a `queued` training job (race-free `UPDATE … WHERE status='queued' RETURNING`),
  streams labeled training data via the cursor-paginated
  `GET /api/training-data`, fits a `RandomForestClassifier`, uploads the
  serialized model to Freki with a `feature_config` JSONB blob, and reports
  status. When `MODEL_UPLOAD_SHARED_SECRET` is set, Nornir sends
  `X-Grimnir-Model-Upload-Secret` on model uploads. When
  `ML_CONTROL_SHARED_SECRET` is set, Nornir sends
  `X-Grimnir-ML-Control-Secret` on daemon/job control writes, and Freki binds
  running-job updates to a per-claim token. Metrics on `:8001`.

- **Völva** (`volva/`) — live inference. Polls `/api/models/active`, hot-swaps
  the in-memory classifier when the active model id changes (refusing models
  whose `feature_config.version` mismatches this build's `FEATURE_VERSION`),
  subscribes to `/api/csi-stream`, maintains a per-receiver sliding window,
  majority-votes across the last N per-receiver predictions, and publishes
  `PUT /api/predictions/current` with `{timestamp, model_id, rooms}`.
  Metrics + `/health` on `:8002`.

Freki persists the latest prediction envelope in Postgres so
`/api/predictions/current` and `/api/predictions/stream` stay correct across
multiple replicas.

Feature extraction is shared: both services import
`csi_models.features.extract_features` from the `mimir` package (gated behind
the `[features]` pip extra). `feature_config.version` is incremented whenever
extractor output changes, which Völva enforces on model load.

**Label carve-out (plan A2):** v1 uses `labels.occupants` as the human-count
label — `occupants` currently includes pets (#14). A predicted room is reported
as `human_count=1` with all other known rooms at `0`.

GPU machines (Tesla P100) are available if a future trainer needs them; the
current `RandomForestClassifier` trains on CPU in seconds on typical datasets.
