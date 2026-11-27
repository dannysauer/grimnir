# ADR: Train and infer in separate services that reach data only through Freki

## Record

| Field | Value |
| --- | --- |
| Date | 2026-04-18 |
| Status | Accepted |
| Owner | Danny Sauer |
| Author | Danny Sauer |
| Scope | Where training and inference run and how they get data. Excludes the features and model family they use. |
| Related | [#9](https://github.com/dannysauer/grimnir/issues/9), [#17](https://github.com/dannysauer/grimnir/issues/17), [#18](https://github.com/dannysauer/grimnir/issues/18), [#19](https://github.com/dannysauer/grimnir/issues/19); commits `d31823c`, `eaadf35`, and `95a3ef2`; [ML pipeline](../architecture/ml-pipeline.md) |
| Implementation | `nornir/`, `volva/`, `freki/src/freki/routers/training_*.py`, `models.py`, `csi_stream.py`, `predictions.py` |

## Business driver

Training wants a machine with a GPU, which isn't the machine that runs the
dashboard. Inference has to run all the time and survive a trainer that's
offline. Neither should need database credentials to do its job.

## Constraints

- Training hosts are other machines on the LAN and may come and go.
- More than one trainer may be running, so two of them can't take the same
  job.
- Inference needs every new CSI row within about a second.

## Decision

**Y statement:** We will run training (Nornir) and inference (Völva) as
separate services that talk to Freki over HTTP and never to the database,
because trainers run on other machines and should need only one URL, so
database credentials stay with Geri and Freki.

Nornir registers with a heartbeat, claims a queued job, pages labeled rows
from `GET /api/training-data`, and uploads the fitted model. Völva polls
`GET /api/models/active`, tails `GET /api/csi-stream`, and writes
`PUT /api/predictions/current`.

- Nornir and Völva MUST NOT connect to PostgreSQL.
- Freki MUST hand a queued job to at most one daemon. The claim is a
  conditional `UPDATE … WHERE status = 'queued' RETURNING`.
- Model artifacts are stored inline in `trained_models` and downloaded through
  Freki.

## Consequences

- Freki is on the path of every CSI row Völva sees. Its stream polls the
  database, so inference lags ingestion by at least one poll interval, and a
  slow consumer can fall behind
  ([#63](https://github.com/dannysauer/grimnir/issues/63)).
- Every capability a trainer needs becomes a Freki endpoint first. That's the
  surface an agent-facing interface would build on.
- Anyone who can reach Freki can reach the training and model endpoints, which
  is why the shared-secret record exists
  ([2026-04-18](2026-04-18-shared-secrets-for-ml-writes.md)).

## Alternatives considered

### Give the ML services direct database access

Issue #9's original plan showed a training query run straight against
`csi_samples`. The same issue notes that trainers "access data via Freki
API", and the implementation issues built it that way. No comparison was
written down. The effect is that a trainer on a GPU host needs one URL and no
database role.

### Train and infer inside Freki

Not recorded as considered. It would tie training to the API host's CPU and
restart inference with every API deploy.
