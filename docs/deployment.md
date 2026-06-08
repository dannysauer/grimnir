# Deployment Guide

Grimnir ships deployment assets under `bifrost/`:

- `bifrost/compose.yaml` for standalone Docker Compose.
- `bifrost/helm/grimnir/` for Kubernetes.
- `bifrost/ansible/` for Ansible-driven Kubernetes installs and upgrades.

PostgreSQL with TimescaleDB is external in all shipped deployment modes.

## Required Database

Set `DATABASE_URL` to a PostgreSQL URL that uses the asyncpg SQLAlchemy driver:

```text
postgresql+asyncpg://csi_user@db.example.com:5432/csi
```

The examples in this repository omit passwords. Use the same URL shape with your
real credentials in `.env`, an uncommitted values file, or a Kubernetes Secret.

On startup, Geri and Freki call `run_migrations(DATABASE_URL)` from the Mimir
package. That code converts the URL to `postgresql+psycopg2://` for synchronous
bootstrap operations, ensures the database exists when allowed, then applies
numbered SQL migrations.

The target database must either already have the `timescaledb` extension
installed, or the configured database role must be able to run
`CREATE EXTENSION timescaledb`. On PostgreSQL 12 and TimescaleDB 2.11, fully
automatic first boot commonly requires an elevated role unless the extension is
preinstalled by an administrator.

Recommended bootstrap, with the extension installed by a database administrator
before the runtime role is used by Grimnir:

```bash
psql -U postgres -c "CREATE DATABASE csi;"
psql -U postgres -d csi -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
createuser -U postgres --pwprompt csi_user
psql -U postgres -c "GRANT ALL ON DATABASE csi TO csi_user;"
psql -U postgres -d csi -c "GRANT CREATE ON SCHEMA public TO csi_user;"
```

After this, start Freki or Geri with `DATABASE_URL`; the bundled Mimir migrations
create and update Grimnir tables.

For a short-lived lab bootstrap, you can grant the runtime role the elevated
permissions required to create TimescaleDB objects, start one service once so
Mimir applies migrations, then revoke the elevation:

```bash
psql -U postgres -c "ALTER USER csi_user WITH SUPERUSER;"
# Start Freki or Geri once and wait for "migrations.done" in the service logs.
psql -U postgres -c "ALTER USER csi_user WITH NOSUPERUSER;"
```

Do not leave the Grimnir runtime role as a superuser in a long-running
deployment. If migrations fail, stop the services and inspect
`schema_migrations` before granting broader privileges again.

## Docker Compose

Compose starts Geri, Freki, Nornir, and Volva. It does not start PostgreSQL.

From the repository root:

```bash
cp .env.example .env
# Edit .env and set DATABASE_URL.
docker compose -f bifrost/compose.yaml up -d
```

Exposed ports:

| Port | Protocol | Service | Purpose |
|------|----------|---------|---------|
| 5005 | UDP | Geri | Muninn CSI packet ingress. |
| 8000 | TCP | Freki | Dashboard, API, `/health`, and `/metrics`. |

Nornir and Volva are internal Compose services. They reach Freki at
`http://freki:8000`.

Verification:

```bash
docker compose -f bifrost/compose.yaml ps
curl -fsS http://127.0.0.1:8000/health
```

Watch Geri logs while a receiver is running:

```bash
docker compose -f bifrost/compose.yaml logs -f geri
```

You should see Geri listening on UDP 5005 and receiver activity after Muninn
starts sending packets.

## Helm

The chart is published as:

```text
oci://ghcr.io/dannysauer/charts/grimnir
```

Minimal install:

```bash
CHART_VERSION=0.1.1
helm install grimnir oci://ghcr.io/dannysauer/charts/grimnir \
  --version "$CHART_VERSION" \
  --set database.url="postgresql+asyncpg://csi_user@db.example.com:5432/csi"
```

The chart also has a GitHub-rendered package entrypoint at
[`bifrost/helm/grimnir/README.md`](../bifrost/helm/grimnir/README.md). Use that
page for the full values reference, secret options, upgrade commands, and
package metadata.

For local chart validation from the repository:

```bash
helm lint bifrost/helm/grimnir \
  --set database.url="postgresql+asyncpg://csi_user@db.example.com:5432/csi"

helm template grimnir bifrost/helm/grimnir \
  --set database.url="postgresql+asyncpg://csi_user@db.example.com:5432/csi"
```

The chart deploys these workloads:

| Workload | Purpose |
|----------|---------|
| Geri Deployment and UDP Service | Receiver packet ingress and TimescaleDB writer. |
| Freki Deployment and Service | Dashboard, API, SSE, health, and metrics. |
| Nornir Deployment and metrics Service | Training daemon. |
| Volva Deployment and Service | Live inference service health and metrics. |

Important values:

| Value | Default | Notes |
|-------|---------|-------|
| `database.url` | Empty | Required unless `database.existingSecret` is set. |
| `database.existingSecret` | Empty | Secret containing the key from `database.secretKey`. |
| `geri.service.type` | `LoadBalancer` | Needed when ESP32 receivers must reach Geri from the LAN. |
| `geri.service.annotations` | `{}` | Use for MetalLB and external-dns annotations. |
| `freki.ingress.enabled` | `false` | Enables dashboard/API ingress. |
| `modelUploadAuth.sharedSecret` | Empty | Creates a Secret for model upload auth. Prefer `existingSecret` on shared clusters. |
| `mlControlAuth.sharedSecret` | Empty | Creates a Secret for Nornir control writes. Prefer `existingSecret` on shared clusters. |
| `prometheus.serviceMonitor.enabled` | `false` | Requires Prometheus Operator CRDs. |
| `grafana.dashboard.enabled` | `false` | Creates a dashboard ConfigMap for a Grafana sidecar. |
| `vpa.enabled` | `false` | Requires Vertical Pod Autoscaler CRDs. |

Example Geri service annotations:

```yaml
geri:
  service:
    annotations:
      metallb.universe.tf/address-pool: default
      external-dns.alpha.kubernetes.io/hostname: csi-aggregator.home.example.com
```

Firmware `AGGREGATOR_HOST` must resolve to the Geri load balancer address.

Verification:

```bash
kubectl get pods,svc -l app.kubernetes.io/instance=grimnir
kubectl rollout status deployment/grimnir-freki
kubectl rollout status deployment/grimnir-geri
kubectl port-forward svc/grimnir-freki 8000:8000
curl -fsS http://127.0.0.1:8000/health
```

## Ansible

The Ansible playbooks wrap Helm installation and values assembly. The deploy
playbook expects a reachable cluster and Helm-capable Kubernetes credentials.

Example:

```bash
ansible-playbook bifrost/ansible/deploy.yaml \
  -e db_url="postgresql+asyncpg://csi_user@db.example.com:5432/csi" \
  -e metallb_pool="default" \
  -e metallb_lb_ip="192.0.2.50" \
  -e freki_hostname="grimnir.home.example.com"
```

Use the Ansible path when you want a repeatable home-cluster deployment with
MetalLB or external-dns inputs. Use direct Helm commands when iterating on chart
changes.

`bifrost/ansible/deploy.yaml` builds and pushes all four service images with the
same `image_tag` value, then deploys the local chart. Use
`bifrost/ansible/install.yaml` when you want the database provisioning path and a
published OCI chart instead.

## Security Notes

- Freki still needs broader dashboard/API authentication before exposure beyond
  a trusted network.
- `MODEL_UPLOAD_SHARED_SECRET` protects model upload writes when configured.
- `ML_CONTROL_SHARED_SECRET` protects Nornir daemon and job-control writes when
  configured.
- Do not commit real database URLs, shared secrets, Wi-Fi passwords, kubeconfigs,
  or firmware `config.local.h`.

## Rollback and Recovery

Compose:

```bash
docker compose -f bifrost/compose.yaml logs --tail=200
docker compose -f bifrost/compose.yaml restart freki geri nornir volva
```

Helm:

```bash
helm history grimnir
REVISION=1
helm rollback grimnir "$REVISION"
kubectl rollout status deployment/grimnir-freki
```

Database migrations are applied at service startup. If a migration checksum
mismatch is reported, stop the deployment and inspect `schema_migrations`
before rolling forward or manually repairing the database.
