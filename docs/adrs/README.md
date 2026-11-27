# Architecture decision records

Each record holds one durable decision, why it won, and what it ruled out.
A change that crosses an Accepted record needs a new record that supersedes
it; see the reading order in [`AGENTS.md`](../../AGENTS.md).

Files are named `YYYY-MM-DD-short-title.md` after the date of the decision.
The records dated before 2026-11-15 were written on that day from commits and
issues, and each one names its sources. Where the original reasoning wasn't
written down, the record says so instead of guessing.

| Date | Decision | Status |
| --- | --- | --- |
| 2026-04-04 | [Apply bundled SQL migrations at service startup](2026-04-04-startup-sql-migrations.md) | Accepted |
| 2026-04-13 | [Keep labeled CSI in its own hypertable and expire raw CSI after 14 days](2026-04-13-separate-training-samples-retention.md) | Accepted |
| 2026-04-18 | [Train and infer in separate services that reach data only through Freki](2026-04-18-ml-services-use-freki-api.md) | Accepted |
| 2026-04-18 | [Share one versioned feature extractor between training and inference](2026-04-18-shared-versioned-feature-extraction.md) | Accepted |
| 2026-04-18 | [Gate machine-only ML writes with optional shared secrets](2026-04-18-shared-secrets-for-ml-writes.md) | Accepted |
| 2026-04-18 | [Store the current prediction in PostgreSQL](2026-04-18-current-prediction-in-postgres.md) | Accepted |
| 2026-04-19 | [Carry CSI over a versioned binary UDP protocol with ACK liveness](2026-04-19-udp-wire-protocol-with-ack-liveness.md) | Accepted |
| 2026-04-19 | [Pin GitHub Actions to full release tags](2026-04-19-pin-actions-to-release-tags.md) | Accepted |
| 2026-11-15 | [Pin GitHub Actions to commit SHAs](2026-11-15-pin-actions-to-commit-shas.md) | Proposed |
| 2026-11-27 | [Defer authentication for the proof of concept, behind one seam](2026-11-27-defer-authentication.md) | Accepted |
