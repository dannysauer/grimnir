# Grimnir — TODO Checklist

Tracked items for follow-up. Check off as completed. Open items are also tracked
as GitHub issues where noted.

---

## Blocking / High Priority

- [x] **Mimir package** — `csi_models` now provides SQLAlchemy ORM models,
      engine/session helpers, and idempotent first-boot SQL bootstrap for
      `geri` and `freki`.
      _(#1)_

---

## CI/CD

- [x] **Renovate integration** — `renovate.json5` added; manages Python deps,
      Docker base images (SHA-pinned), GitHub Actions (SHA-pinned), and
      PlatformIO platform versions. Updates grouped per manager.
      _(#2)_

- [ ] **Supply chain security** — SBOM generation (`syft`), image signing (`cosign`),
      and VEX/attestation publishing. Deferred from initial PoC; add before any
      public/production use.
      _(#3)_

---

## Testing

- [ ] **pytest + pytest-asyncio** test suite for `geri` and `freki`.
      Priority: `geri/src/geri/parser.py` (pure function, easy to unit test).
      _(#4)_

---

## Security

- [ ] **HTTPS + auth for Freki** — no authentication currently; put behind nginx
      or an API gateway with at minimum HTTP Basic Auth before exposing beyond
      localhost. Narrow mitigation: `MODEL_UPLOAD_SHARED_SECRET` now gates
      `POST /api/models` when configured, but broader API auth is still open.
      _(#5)_

- [x] **Shared-secret gate for model uploads** — optional
      `MODEL_UPLOAD_SHARED_SECRET` now requires
      `X-Grimnir-Model-Upload-Secret` on `POST /api/models`, and Nornir sends
      the same header automatically during model upload.
      _(#29)_

- [x] **SQL injection in `labels.py`** — `list_labels` previously built a raw SQL
      `INTERVAL` clause from the user-supplied `minutes` parameter; replaced with
      `timedelta(minutes=minutes)` via the ORM.
      _(#6)_

---

## Data Quality

- [ ] **Phase calibration** — raw phase data is contaminated by hardware offsets.
      Amplitude is reliable for presence detection; phase needs a sanitisation /
      calibration preprocessing step before ML training.
      _(#7)_

---

## Frontend

- [x] **Hlidskjalf SSE error handling** — error banner with countdown now shown
      on disconnect; auto-reconnects with exponential backoff (1 s → 30 s cap);
      "reconnect now" button resets the backoff immediately.
      _(#8)_

---

## Helm / Kubernetes

- [ ] **Helm: empty `loadBalancerIP`** — when `geri.service.loadBalancerIP` is
      not set, the template must omit the field entirely rather than emit an
      empty string, which some cloud providers reject.
      _(already guarded by `if` in the current template)_

---

## ML Pipeline

- [x] **ML training pipeline** — shared feature extraction in
      `csi_models.features`; Freki routers for training jobs / daemons / models /
      training data / predictions / csi-stream; Nornir training daemon
      (`nornir/`) claiming jobs and uploading sklearn models; Völva inference
      service (`volva/`) consuming `/api/csi-stream` and publishing room
      predictions; Hlidskjalf Training + Models tabs; compose + Helm chart for
      both new services. Human-count label is `labels.occupants` (see #14).
      _(#9 / #16 / #17 / #18 / #19 / #20 / #21)_

- [ ] **Pets vs humans in `occupants`** — v1 ML label is the raw `occupants`
      column, which currently includes pets. Split once tag inputs identify
      humans only.
      _(#14)_
