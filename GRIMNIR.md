# Grimnir Naming Reference

Grimnir is one of Odin's names. In this project, it describes a system that
observes Wi-Fi CSI signals to infer room-level presence without using cameras.

The monorepo uses Norse names for the major components. These names are current
project vocabulary, not a pending rename plan.

| Component | Name | Path | Role |
|-----------|------|------|------|
| Transmitter firmware | Huginn | `firmware/huginn/` | ESP32-S3 board that broadcasts beacon frames for CSI capture. |
| Receiver firmware | Muninn | `firmware/muninn/` | ESP32-S3 boards that capture CSI and stream UDP packets to Geri. |
| Aggregator service | Geri | `geri/` | Receives UDP CSI packets, sends receiver ACKs, and writes to TimescaleDB. |
| Backend API | Freki | `freki/` | FastAPI service for the dashboard, REST API, SSE streams, models, and metrics. |
| Training daemon | Nornir | `nornir/` | Claims training jobs from Freki, trains models, and uploads artifacts. |
| Inference service | Volva | `volva/` | Consumes live CSI from Freki and publishes current room predictions. |
| Frontend dashboard | Hlidskjalf | `hlidskjalf/` | Single-file web dashboard for live data, labeling, training, and model management. |
| Database package | Mimir | `mimir/` | Shared SQLAlchemy models, SQL migrations, and feature extraction helpers. |
| Deployment assets | Bifrost | `bifrost/` | Docker Compose, Helm chart, and Ansible playbooks. |

## Naming Conventions

- Python package names are lowercase: `geri`, `freki`, `nornir`, `volva`,
  and `csi-models`.
- Docker images are published under `ghcr.io/dannysauer/grimnir/COMPONENT`.
- The Helm chart name and expected release name are both `grimnir`.
- Firmware receiver names should be stable and location-oriented, such as
  `grimnir-rx-office` or `grimnir-rx-upstairs`.
- DNS names may use descriptive service names such as
  `csi-aggregator.home.arpa` or `geri.home.arpa`; choose one convention and
  keep firmware, Helm, and local DNS aligned.
