# Grimnir — TODO Checklist

Tracked items for follow-up. Check off as completed. Open items are also tracked
as GitHub issues where noted.

---

## Blocking / High Priority

- [ ] **Mimir package** — SQLAlchemy ORM models, Alembic migrations, engine factory,
      and `migrate.py`. Both `geri` and `freki` import `from csi_models import ...`
      and cannot run until this is built.
      _(#1)_

---

## CI/CD

- [ ] **Renovate integration** — add `renovate.json` so dependency version bumps
      are automated (chore commits → patch releases).
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

- [ ] **SQL injection in `labels.py`** — `list_labels` builds a raw SQL
      `INTERVAL` clause from the user-supplied `minutes` parameter. Replace with
      a parameterised query or ORM expression.
      _(#6)_

---

## Data Quality

- [ ] **Phase calibration** — raw phase data is contaminated by hardware offsets.
      Amplitude is reliable for presence detection; phase needs a sanitisation /
      calibration preprocessing step before ML training.
      _(#7)_

---

## Frontend

- [ ] **Hlidskjalf SSE error handling** — on SSE connection failure the UI only
      shows a colour change on the status dot; add a visible error banner and
      auto-reconnect with exponential backoff.
      _(#8)_

---

## Helm / Kubernetes

- [ ] **Helm: empty `loadBalancerIP`** — when `geri.service.loadBalancerIP` is
      not set, the template must omit the field entirely rather than emit an
      empty string, which some cloud providers reject.
      _(already guarded by `if` in the current template)_

---

## ML Pipeline

- [ ] **ML training pipeline** — training data is collected via the Label tab;
      no training code exists yet. GPU machines (Tesla P100) are available.
      Start with classical features (mean/variance per subcarrier) before deep
      learning.
      _(#9)_
