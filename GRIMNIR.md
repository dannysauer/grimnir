# Grimnir — Project Naming & Structure Reference

> **For Claude Code**: Use this document when reorganizing the monorepo.
> Append or `@`-reference this file alongside the existing `CLAUDE.md`.

## Project Name

**Grimnir** — Norse: "the Hooded One," one of Odin's names when he travels
in disguise as an observer. Fits the project's purpose: silent observation of
Wi-Fi CSI to detect and locate people.

## Component Names (Norse / Raven Theme)

| Component | Name | Origin | Role |
|-----------|------|--------|------|
| Transmitter firmware | **Huginn** | Odin's raven ("thought") | ESP32-S3 that broadcasts beacon frames for CSI capture |
| Receiver firmware | **Muninn** | Odin's raven ("memory") | ESP32-S3(s) that capture CSI and stream UDP to aggregator |
| Aggregator service | **Geri** | One of Odin's wolves | Receives UDP CSI packets, writes to TimescaleDB |
| Backend API | **Freki** | Odin's other wolf | FastAPI REST + SSE serving data to the frontend |
| Frontend dashboard | **Hlidskjalf** | Odin's high seat (sees all) | Web UI for live CSI visualization and labeling |
| Database schema | **Mimir** | Wise being; keeper of knowledge | TimescaleDB storing all CSI data |
| Deployment/infra | **Bifrost** | The rainbow bridge | Compose, Helm, Ansible — bridges dev to production |
| ML training daemon | **Nornir** (`nornir/`) | The three Norns who weave fate | Polls for training jobs, fits sklearn models, uploads results |
| Inference service | **Völva** (`volva/`) | Norse seeress/prophetess | Applies active model to live CSI; exposes predictions API |

> Pick and choose from this table. Not every component needs a raven/Norse name
> if it feels forced — practical names are fine for minor pieces.

## Monorepo Layout

Rename from `csi-project/` to `grimnir/`:

```
grimnir/
├── CLAUDE.md                 # Existing Claude Code instructions
├── GRIMNIR.md                # This file (naming reference)
├── README.md
├── firmware/
│   ├── config.h              # Shared firmware config (Wi-Fi, aggregator host, etc.)
│   ├── huginn/               # Was: transmitter/
│   │   ├── main/main.c
│   │   ├── CMakeLists.txt
│   │   └── sdkconfig.defaults
│   └── muninn/               # Was: receiver/
│       ├── main/main.c
│       ├── CMakeLists.txt
│       └── sdkconfig.defaults
│
├── geri/                     # Was: aggregator/
│   ├── src/geri/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── parser.py
│   │   └── db.py
│   ├── pyproject.toml
│   └── Dockerfile
│
├── freki/                    # Was: backend/
│   ├── src/freki/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   └── routers/
│   ├── pyproject.toml
│   └── Dockerfile
│
├── hlidskjalf/               # Was: frontend/
│   └── index.html
│
├── mimir/                    # Was: db/
│   └── 001_schema.sql
│
└── bifrost/                  # Was: compose/ + helm/ + ansible/
    ├── compose.yaml
    ├── helm/
    └── ansible/
```

## Rename Mapping (Quick Reference)

Use this when doing the actual `git mv` operations:

```
firmware/transmitter/  →  firmware/huginn/
firmware/receiver/     →  firmware/muninn/
aggregator/            →  geri/
backend/               →  freki/
frontend/              →  hlidskjalf/
db/                    →  mimir/
compose/ + helm/ + ansible/  →  bifrost/
```

## Internal References to Update

After renaming directories, grep and update these:

- **pyproject.toml** `name` and `packages` fields (e.g. `csi-aggregator` → `geri`)
- **pyproject.toml** `[project.scripts]` entry points
- **Dockerfile** `COPY` paths and module names
- **compose.yaml** / **Helm values** — build context paths, service names
- **Ansible playbook** — any hardcoded paths
- **CMakeLists.txt** — `project()` names (e.g. `project(csi_transmitter)` → `project(huginn)`)
- **README.md** — directory references, architecture diagram
- **Import statements** in Python code (e.g. `from csi_aggregator` → `from geri`)
- **config.h** `#include` relative paths if they changed
- **Log tags** in firmware — update `LOG_TAG_*` if desired (optional, cosmetic)

## Naming Conventions Going Forward

- **New Python packages**: lowercase Norse name, underscores only if multi-word
- **Docker image tags**: `grimnir/geri:latest`, `grimnir/freki:latest`
- **Helm release**: `grimnir`
- **DNS hostname**: keep `csi-aggregator.home.arpa` or switch to `geri.home.arpa` — your call
- **Git repo**: `grimnir` (on GitHub: `dannysauer/grimnir`)
