# Grimnir data model

> **Summary:** One external PostgreSQL database with TimescaleDB holds
> everything: raw CSI for 14 days, labeled CSI indefinitely, the rooms and
> labels a person enters, and the training queue, model registry, and current
> prediction. The numbered SQL files under `mimir/src/csi_models/sql/` are
> the authoritative schema.

## Where the schema lives

The schema is a sequence of numbered SQL files bundled in the `csi-models`
package. Geri and Freki apply the pending ones at startup, under an advisory
lock, and record each file's checksum in `schema_migrations`. The
[migration record](../adrs/2026-04-04-startup-sql-migrations.md) explains why.

The SQLAlchemy models in `mimir/src/csi_models/models.py` describe the same
tables for queries. They leave out indexes, policies, and most server
defaults, so read the SQL when those matter.

The `.sql` files directly under `mimir/` are an older reference copy. They're
missing migrations `003` and `005`, so don't rely on them
([#68](https://github.com/dannysauer/grimnir/issues/68)).

## Tables

| Table | Kind | Holds |
| --- | --- | --- |
| `receivers` | table | One row per Muninn board. Geri adds a row the first time it sees a receiver name. |
| `receiver_heartbeats` | table | Last-seen time and source address for each receiver. |
| `csi_samples` | hypertable | One row per CSI packet: receiver, transmitter MAC, RSSI, channel, bandwidth, amplitude and phase arrays, and a nullable room `label`. |
| `csi_variance_1min` | continuous aggregate | Per-minute sample count, average RSSI, and RSSI standard deviation for each receiver, for the dashboard charts. |
| `rooms` | table | The rooms a label may name, with a floor number. The room name is the primary key. |
| `labels` | table | Time ranges a person marked as "this room, this many occupants", with optional notes. |
| `training_samples` | hypertable | A copy of every labeled `csi_samples` row, with no retention policy. |
| `training_daemons` | table | One row per Nornir instance, updated by its heartbeat. |
| `training_jobs` | table | The job queue: spec, status, claiming daemon, claim token, heartbeat, and error. |
| `trained_models` | table | Model metadata, metrics, `feature_config`, and the serialized model itself. At most one row is active. |
| `current_predictions` | table | A single row holding the latest prediction envelope. |
| `schema_migrations` | table | Applied migration versions and checksums. |

## How a label reaches the training set

A label is a time range and a room. When Freki saves one, it writes the room
name into `csi_samples.label` for every sample in that range, and copies those
rows into `training_samples`. Deleting a label clears the range and reapplies
any other label that overlaps it. Renaming a room rewrites the stored name in
`labels`, `csi_samples`, and `training_samples` in one transaction, with one
exception: if the database role may not update `training_samples`, the rename
still commits and that table keeps the old name
([#107](https://github.com/dannysauer/grimnir/issues/107)).

Label writes on large ranges are slow, so Freki runs them with lock and
statement timeouts. A rename or delete that can't finish in time returns `503`
and changes nothing.

The copy into `training_samples` is best effort on both paths. After a label
is created or deleted, Freki syncs the range in a separate step, and a failure
there is logged and not retried, which can leave the two tables out of step
([#64](https://github.com/dannysauer/grimnir/issues/64)). The sync after a
delete removes the range's training rows and rebuilds them from `csi_samples`.
Once the raw samples have expired there is nothing to rebuild from, so
deleting or correcting a label older than 14 days erases its training rows
([#105](https://github.com/dannysauer/grimnir/issues/105)).

A label says one thing about a time range: a room name and an occupant count.
It can't say who was there, whether an occupant was a pet, or what they were
doing ([#14](https://github.com/dannysauer/grimnir/issues/14)).

## Retention and compression

| Hypertable | Chunk interval | Compressed after | Dropped after |
| --- | --- | --- | --- |
| `csi_samples` | 2 days | 2 days | 14 days |
| `training_samples` | 90 days | 30 days | never |

Raw samples expire, and no policy expires labeled ones. A time range has to be labeled
within 14 days of capture, or its samples are gone. The
[retention record](../adrs/2026-04-13-separate-training-samples-retention.md)
has the reasoning.

`csi_variance_1min` refreshes once a minute.

## What a sample doesn't record

Each sample's `time` is the moment Geri parsed the packet, not the moment the
receiver captured it. The packet's device timestamp is parsed and then
discarded, and there is no sequence number, so lost packets leave no trace.
`raw_bytes` exists on both hypertables but Geri never fills it.

Amplitude and phase are stored as flat `REAL[]` arrays of
`antenna_count * subcarrier_count` values. The `antenna_count` a receiver
reports is unreliable
([#66](https://github.com/dannysauer/grimnir/issues/66)).

## Database privileges

The role in `DATABASE_URL` runs migrations, so it needs to create tables in
the `public` schema. On a fresh database, either an administrator installs
the `timescaledb` extension first or the role must be allowed to create it.
The [deployment guide](../deployment.md#required-database) has the commands.
