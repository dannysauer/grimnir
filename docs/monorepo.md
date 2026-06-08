# Monorepo Guide

Grimnir is a heterogeneous monorepo. It contains firmware, Python packages,
database migrations, a static dashboard, container definitions, and deployment
assets. Work from the repository root unless a command explicitly says to
change directories.

## Component Map

| Component | Path | Runtime role | Build or test entry point |
|-----------|------|--------------|---------------------------|
| Huginn | `firmware/huginn/` | ESP32-S3 transmitter firmware. Sends frames for CSI capture. | `idf.py build` or `pio run` from `firmware/huginn/`. |
| Muninn | `firmware/muninn/` | ESP32-S3 receiver firmware. Sends CSI UDP packets to Geri. | `idf.py build` or `pio run` from `firmware/muninn/`. |
| Geri | `geri/` | UDP receiver and TimescaleDB writer. | `pytest geri/tests` from the repo root. |
| Freki | `freki/` | FastAPI backend, dashboard server, REST API, SSE streams, and metrics. | `pytest freki/tests` from the repo root. |
| Nornir | `nornir/` | Training daemon for queued model jobs. | Package entry point: `nornir`. |
| Volva | `volva/` | Live inference service. | Package entry point: `volva`. |
| Hlidskjalf | `hlidskjalf/` | Static dashboard served by Freki. | Open through Freki; no separate build step. |
| Mimir | `mimir/` | Shared database and feature package named `csi-models`. | Installed by service Dockerfiles before the service package. |
| Bifrost | `bifrost/` | Compose, Helm, and Ansible deployment assets. | `docker compose`, `helm lint`, `helm template`, or `ansible-playbook`. |

## Shared Package Boundaries

`mimir/` builds the `csi-models` Python package. The service packages import it
for shared database models and first-boot migrations. Nornir, Volva, and Freki
also use the `[features]` extra for ML feature extraction.

The service Dockerfiles copy and install `mimir/` before installing their own
package:

```dockerfile
COPY mimir/ /mimir
RUN pip install --no-cache-dir /mimir
```

For Nornir and Volva, the install includes the feature extra:

```dockerfile
RUN pip install --no-cache-dir "/mimir[features]"
```

Because of this dependency, Docker build context must be the repository root,
not the individual service directory.

## Command Matrix

| Task | Working directory | Command | Expected result |
|------|-------------------|---------|-----------------|
| Install pinned tools | Repository root | `asdf install` | Python, Node.js, Helm, and pre-commit versions from `.tool-versions` are installed. |
| Run all configured pre-commit hooks | Repository root | `pre-commit run --all-files` | Ruff, formatting, shell, GitHub Actions, YAML/JSON, and hygiene checks pass. |
| Run Geri tests | Repository root | `pytest geri/tests` | Parser and aggregator tests pass. |
| Run Freki tests | Repository root | `pytest freki/tests` | API router and auth tests pass. |
| Validate Compose configuration | Repository root | `DATABASE_URL='postgresql+asyncpg://csi_user@db.example.com:5432/csi' docker compose -f bifrost/compose.yaml config` | Compose renders the full four-service stack. |
| Lint Helm chart | Repository root | `helm lint bifrost/helm/grimnir --set database.url='postgresql+asyncpg://csi_user@db.example.com:5432/csi'` | Chart lint passes. |
| Render Helm chart | Repository root | `helm template grimnir bifrost/helm/grimnir --set database.url='postgresql+asyncpg://csi_user@db.example.com:5432/csi'` | Kubernetes manifests render. |
| Validate Helm values schema | Repository root | `helm lint bifrost/helm/grimnir --set database.url='postgresql+asyncpg://csi_user@db.example.com:5432/csi'` | `values.schema.json` accepts the supplied values and rejects invalid shapes. |
| Build Huginn firmware | `firmware/huginn/` | `idf.py set-target esp32s3 && idf.py build` | ESP-IDF produces firmware build output. |
| Build Muninn firmware | `firmware/muninn/` | `idf.py set-target esp32s3 && idf.py build` | ESP-IDF produces firmware build output. |
| Build firmware with PlatformIO | `firmware/huginn/` or `firmware/muninn/` | `pio run` | PlatformIO builds using `framework = espidf`. |

## Development Notes

- The root `pyproject.toml` configures Ruff and pytest for the whole repo. It
  is not an installable package.
- Each Python service has its own `pyproject.toml` and console entry point.
- `docs/style-guides/google/` is vendored external content. Do not edit it as
  project documentation unless updating the subtree intentionally.
- The checked-in SQL under `mimir/` is both reference material and the source
  for packaged first-boot migrations.
- `TODO.md` is a tracking mirror for known follow-up work. It is not a
  replacement for reader-facing setup, API, deployment, or protocol docs.

## Documentation Ownership

When changing a component, update the docs that describe its public behavior:

| Change type | Docs to check |
|-------------|---------------|
| Freki route, request body, response body, auth, or SSE behavior | `docs/api-reference.md`, `CLAUDE.md`, and tests. |
| Muninn packet layout or parser behavior | `docs/udp-wire-protocol.md`, `docs/firmware-build-and-flash.md`, `geri/src/geri/parser.py`, and parser tests. |
| Compose, Helm, Ansible, environment variables, ports, or image names | `docs/deployment.md`, `README.md`, `.env.example`, `bifrost/helm/grimnir/README.md`, `bifrost/helm/grimnir/values.yaml`, and `bifrost/helm/grimnir/values.schema.json`. |
| Firmware setup or flash workflow | `docs/firmware-build-and-flash.md`, `firmware/config.h`, and `firmware/config.local.h.example`. |
| Component names, paths, or package boundaries | `README.md`, `GRIMNIR.md`, `docs/monorepo.md`, and `CLAUDE.md`. |
