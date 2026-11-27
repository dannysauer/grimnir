# ADR: Store the current prediction in PostgreSQL

## Record

| Field | Value |
| --- | --- |
| Date | 2026-04-18 |
| Status | Accepted |
| Owner | Danny Sauer |
| Author | Danny Sauer |
| Scope | Where Freki keeps the latest prediction that Völva publishes. Excludes prediction history, which isn't kept. |
| Related | [#28](https://github.com/dannysauer/grimnir/issues/28); commit `69856f8`; migration `008` |
| Implementation | `freki/src/freki/routers/predictions.py`, `mimir/src/csi_models/sql/008_current_predictions.sql` |

## Business driver

Home Assistant and the dashboard ask Freki where people are. The Helm chart
can run more than one Freki replica, and the first version kept the latest
prediction in a Python global, so a read could land on a replica that never
received the write.

## Constraints

- PostgreSQL is the only shared state the services have.
- Völva publishes only when its result changes, at most once per completed
  window, so writes are infrequent.

## Decision

**Y statement:** We will store the latest prediction envelope as a single row
in `current_predictions`, because process memory isn't shared between Freki
replicas, so every replica answers `GET /api/predictions/current` and the
prediction stream with the same state.

`PUT /api/predictions/current` upserts row `id = 1`. The stream endpoint polls
that row and emits when it changes.

- Freki MUST NOT keep prediction state in process memory.
- Only the latest envelope is stored. Nothing depends on prediction history.

## Consequences

- Each stream client costs one polling query loop against the database.
- There is no record of past predictions, so nothing can answer "where was
  everyone at 2 a.m." or score live accuracy against later labels. Sleep and
  occupancy history would need a new table and a superseding record.

## Alternatives considered

### Keep the prediction in process memory

This was the original implementation. Issue #28 showed that it made
multi-replica Freki return stale or missing predictions depending on which
replica served the request.
