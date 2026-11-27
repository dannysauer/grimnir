# Grimnir quality attributes

> **Summary:** The requirements Grimnir has to keep, each with a stable ID
> that tests and checks cite. Most are still unverified: the test suites
> cover the packet parser and the secret checks, and little else runs against
> a real database or real firmware.

Requirements use the keywords in [BCP 14](https://www.rfc-editor.org/info/bcp14):
MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY, which carry that meaning only in
capitals. IDs never change and are never reused; a retired requirement keeps
its ID with a note saying why it was retired.

A test that verifies a requirement names its ID in a comment. `unverified`
means no test or check names the ID yet. It doesn't mean the behavior is
broken.

Freki has tests that touch several of the unverified rows, such as job claims
and room renames. They replay canned database results and never execute SQL,
so they aren't counted here
([#117](https://github.com/dannysauer/grimnir/issues/117)).

No requirement states an accuracy or latency target yet. Those belong here
once the [sensing roadmap](../design/2026-11-15-sensing-roadmap.md) settles
what to measure.

## Ingestion

| ID | Requirement | Verified by |
| --- | --- | --- |
| GRM-001 | Geri MUST accept Muninn packet versions 1 and 2. | `geri/tests/test_parser.py` |
| GRM-002 | Geri MUST reject a datagram with a wrong magic number, an unknown version, a short header, or a short payload. | `geri/tests/test_parser.py` |
| GRM-003 | Geri MUST register a receiver on its first valid packet, with no manual setup. | unverified |
| GRM-004 | Geri MUST NOT send ACKs to one sender address more often than `ACK_INTERVAL_S`. | `geri/tests/test_main.py` |
| GRM-005 | Muninn MUST discard CSI from any transmitter other than the configured `HUGINN_MAC`. | unverified |
| GRM-006 | Muninn MUST start recovery without a person when CSI is flowing and no ACK has arrived within `RECEIVER_WATCHDOG_ACK_TIMEOUT_S`. | unverified |

## Data integrity

| ID | Requirement | Verified by |
| --- | --- | --- |
| GRM-010 | Applying migrations to a database that's already current MUST change nothing. | unverified |
| GRM-011 | A service MUST refuse to start when an applied migration's recorded checksum differs from the bundled file. | unverified |
| GRM-012 | Labeled CSI in `training_samples` MUST NOT be removed by a retention policy. | unverified |
| GRM-013 | A room rename MUST update `labels`, `csi_samples`, and `training_samples` in one transaction, or change none of them. | unverified |
| GRM-014 | Freki MUST allow at most one active model. | unverified |

## Training and inference

| ID | Requirement | Verified by |
| --- | --- | --- |
| GRM-020 | Freki MUST hand a queued training job to at most one daemon. | unverified |
| GRM-021 | Freki MUST fail a running job whose heartbeat is older than `ORPHAN_TIMEOUT_S`. | unverified |
| GRM-022 | Nornir and Völva MUST compute features with `csi_models.features.extract_features`. | unverified |
| GRM-023 | Völva MUST refuse a model whose `feature_config.version` differs from its own `FEATURE_VERSION`. | unverified |
| GRM-024 | Völva MUST keep serving the loaded model when a model refresh fails. | unverified |
| GRM-025 | Every Freki replica MUST return the same current prediction. | unverified |

## Security

| ID | Requirement | Verified by |
| --- | --- | --- |
| GRM-030 | When `MODEL_UPLOAD_SHARED_SECRET` is set, Freki MUST reject a model upload that lacks the matching `X-Grimnir-Model-Upload-Secret` header. | `freki/tests/test_ml_auth.py` checks the header comparison; no test checks that the route uses it |
| GRM-031 | When `ML_CONTROL_SHARED_SECRET` is set, Freki MUST reject a daemon heartbeat or a job claim, heartbeat, complete, or fail call that lacks the matching `X-Grimnir-ML-Control-Secret` header. | `freki/tests/test_ml_auth.py` checks the header comparison; no test checks that the routes use it |
| GRM-032 | Freki MUST reject a job heartbeat, complete, or fail call that doesn't carry the claiming daemon's id and claim token. | unverified |
| GRM-033 | Nornir and Völva MUST NOT connect to PostgreSQL. | unverified |
| GRM-034 | The repository MUST NOT contain Wi-Fi credentials, database passwords, or shared secrets. | `detect-secrets` hook in `.pre-commit-config.yaml` |

## Operability

| ID | Requirement | Verified by |
| --- | --- | --- |
| GRM-040 | Every Python service MUST write its logs as one JSON object per line. | unverified |
| GRM-041 | Every Python service MUST expose Prometheus metrics. | unverified |
| GRM-042 | Völva's `/health` MUST return `503` when its model-refresh loop or inference loop has stopped. | unverified |
