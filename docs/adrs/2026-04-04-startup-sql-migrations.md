# ADR: Apply bundled SQL migrations at service startup

## Record

| Field | Value |
| --- | --- |
| Date | 2026-04-04 |
| Status | Accepted |
| Owner | Danny Sauer |
| Author | Danny Sauer |
| Scope | How the PostgreSQL schema is defined, shipped, and applied. Excludes what the schema contains. |
| Related | Commits `30498bf` and `aee7960`; [#1](https://github.com/dannysauer/grimnir/issues/1); [data model](../architecture/data-model.md) |
| Implementation | `mimir/src/csi_models/migrate.py`, `mimir/src/csi_models/sql/` |
| Revisit when | A migration needs to run outside a transaction, or a second checksum mismatch blocks a deployment ([#68](https://github.com/dannysauer/grimnir/issues/68)). |

## Business driver

Geri and Freki both need the schema before they can do anything, and a home
deployment has nobody on call to run a migration step by hand. A fresh install
has to come up from an empty database with one `DATABASE_URL`.

## Constraints

- Most of the schema's value is TimescaleDB DDL: hypertables, compression
  policies, retention policies, and a continuous aggregate. An ORM can't
  express any of it.
- Geri and Freki start independently and may start at the same time.
- The services use the asyncpg driver at runtime, and the migration runner is
  synchronous.

## Decision

**Y statement:** We will keep the schema as numbered SQL files bundled inside
the `csi-models` package, and Geri and Freki will apply the pending files at
startup under a PostgreSQL advisory lock, because the schema is mostly
TimescaleDB DDL that only SQL can state, so a deployment needs no separate
migration step.

`run_migrations()` records each applied file and its SHA-256 checksum in
`schema_migrations`. It converts the runtime URL to the psycopg2 driver for
this one synchronous job.

- An applied migration file MUST NOT be edited. A checksum mismatch stops
  every service at startup.
- A schema change MUST arrive as a new numbered file under
  `mimir/src/csi_models/sql/`.
- The SQL files are authoritative. The SQLAlchemy models describe the tables
  for queries and MAY omit indexes, policies, and server defaults.

## Consequences

- The role in `DATABASE_URL` needs DDL rights, and on a fresh database either
  the `timescaledb` extension is already installed or the role can create it.
- Editing an applied file breaks every existing install. That happened once:
  rooms DDL was added to `001` and had to move to `004` (commit `c171583`).
- A checksum mismatch has no repair path short of editing `schema_migrations`
  by hand ([#68](https://github.com/dannysauer/grimnir/issues/68)).
- Each file runs as one transaction, which TimescaleDB restricts for some
  statements ([#68](https://github.com/dannysauer/grimnir/issues/68)).

## Alternatives considered

### Alembic

Issue #1 and commit `30498bf` planned Alembic migrations generated from the
ORM models. The bootstrap that shipped in `aee7960` used numbered SQL instead.
No comparison was written down. The practical difference is that Alembic
autogeneration can't see hypertables or policies, so every migration would
have been hand-written SQL inside a Python wrapper.

### Raw asyncpg with no SQLAlchemy

An earlier draft used asyncpg directly (commit `19b7dd2`). It was reverted the
same day in `30498bf`, whose message calls it "not the intended architecture":
both services were meant to share models and run migrations at startup.
