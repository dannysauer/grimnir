# ADR: Keep labeled CSI in its own hypertable and expire raw CSI after 14 days

## Record

| Field | Value |
| --- | --- |
| Date | 2026-04-13 |
| Status | Accepted |
| Owner | Danny Sauer |
| Author | Danny Sauer |
| Scope | How long CSI samples are kept and where labeled samples live. Excludes the label schema itself. |
| Related | Commits `257508c`, `83acc59`, and `3e6f21d`; migrations `002`, `003`, and `005`; [data model](../architecture/data-model.md) |
| Implementation | `mimir/src/csi_models/sql/002_training_samples.sql`, `freki/src/freki/routers/labels.py`, `freki/src/freki/routers/rooms.py` |
| Revisit when | Training needs unlabeled history older than 14 days, such as self-supervised pretraining or an "empty house" baseline. |

## Business driver

Receivers produce CSI rows around the clock, and almost none of them are ever
labeled. Keeping all of it for 90 days cost storage without helping training.
The rows that do get a label are the training set and have to outlive any
retention window.

## Constraints

- Labeling happens after the fact, from a phone, usually within a day or two.
- Rewriting labels in compressed chunks is slow and has hung label saves
  ([#49](https://github.com/dannysauer/grimnir/issues/49)), so the usual
  labeling window should end before compression begins.

## Decision

**Y statement:** We will copy labeled rows into a `training_samples`
hypertable with no retention policy and drop raw `csi_samples` chunks after 14
days, because unlabeled CSI loses most of its value within days while labeled
CSI is the training set, so storage stays bounded and no training data
expires.

`csi_samples` uses 2-day chunks and compresses them after 2 days.
`training_samples` uses 90-day chunks and compresses after 30 days.

- `csi_samples.label` and `training_samples.label` MUST agree for every row
  that exists in both. Freki keeps them in step with one bulk statement per
  label write.
- Training MUST read from `training_samples`. `csi_samples` is a fallback only
  for installs where `training_samples` is unreadable.

## Consequences

- A time range has to be labeled within 14 days of capture. After that the
  raw rows are gone.
- Every label write and room rename touches two hypertables. The sync is
  where most of the label bugs have been
  ([#64](https://github.com/dannysauer/grimnir/issues/64),
  [#101](https://github.com/dannysauer/grimnir/issues/101)).
- Unlabeled periods can't be mined later. A feature that needs "what the
  house looks like empty at 3 a.m. last month" has to label that period inside
  the window.
- A change to how raw packets are interpreted can't be replayed over stored
  data at all. Both tables have a `raw_bytes` column, and Geri never fills
  it.

## Alternatives considered

### Keep the original single table with 90-day retention

Migration `001` kept everything in `csi_samples` for 90 days and compressed
after 7. Commit `257508c` replaced it because "unlabeled raw data has little
value after a few days", and labeled rows would still have expired at day 90.

### Sync with a row-level trigger

Migration `002` first synced the two tables with an `AFTER UPDATE` trigger on
`csi_samples.label`. Labeling a five-minute window updates about 11,000 rows,
and the trigger ran once for each, which timed out asyncpg and returned a 500
to the phone. Commit `3e6f21d` dropped the trigger in migration `005` and
moved the sync into Freki as one bulk statement.
