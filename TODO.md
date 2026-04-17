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
      localhost.
      _(#5)_

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

- [ ] **ML training pipeline** — implementation tracked by issues #16–21 (see #9
      for overview). Infrastructure complete; awaiting labeled training data.
      _(#9, #16, #17, #18, #19, #20, #21)_

- [ ] **Mimir schema migration** — `training_daemons`, `training_jobs`, and
      `trained_models` tables added to SQL bootstrap; apply to production DB on
      next Freki startup (idempotent).
      _(#16)_

- [ ] **Phase calibration** — amplitude-only model first; add phase after
      validating accuracy. See calibration approach in conversation history.
      _(#7)_

- [ ] **Per-species pet tracking** — `pet_count` column planned for `labels`
      table; deferred until human-count model is validated.
      _(#14)_
