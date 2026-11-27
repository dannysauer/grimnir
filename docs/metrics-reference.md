# Metrics reference

Each Python service exposes Prometheus metrics. The Helm chart can create
`ServiceMonitor` resources and a Grafana dashboard `ConfigMap`; both are off
by default. Enable them with `prometheus.serviceMonitor.enabled` and
`grafana.dashboard.enabled`.

## Endpoints

| Service | Address | Configured by |
| --- | --- | --- |
| Geri | `:8001/metrics` | `METRICS_PORT`, default `8001` |
| Freki | `:8000/metrics` | `PORT`, default `8000` |
| Nornir | `:8001/metrics` | `METRICS_PORT`, default `8001` |
| Völva | `:8002/metrics` | `PORT`, default `8002` |

## Geri

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `geri_packets_received_total` | counter | `receiver_name` | Packets parsed successfully. |
| `geri_packets_invalid_total` | counter | none | Datagrams the parser rejected. |
| `geri_packets_dropped_total` | counter | none | Packets dropped because the write queue was full. |
| `geri_batch_writes_total` | counter | `status` (`success`, `error`) | Batch inserts attempted. |
| `geri_batch_write_duration_seconds` | histogram | none | Time spent on each batch insert. |
| `geri_batch_size_rows` | histogram | none | Rows per batch. |
| `geri_receiver_last_seen_timestamp_seconds` | gauge | `receiver_name` | Unix time of the last recorded heartbeat. |

## Freki

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `http_request_duration_seconds` | histogram | `handler`, `method`, `status` | Request latency, from `prometheus-fastapi-instrumentator`. |
| `freki_sse_connections_active` | gauge | none | Open `/api/stream` connections. `/api/csi-stream` and `/api/predictions/stream` aren't counted. |

## Nornir

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `nornir_jobs_claimed_total` | counter | none | Training jobs claimed. |
| `nornir_jobs_completed_total` | counter | none | Training jobs finished successfully. |
| `nornir_jobs_failed_total` | counter | `stage` (`train`, `upload`, `report`) | Training jobs that failed, by stage. A failure while fetching data counts as `train`. |
| `nornir_training_duration_seconds` | histogram | none | Time spent fitting a model. |
| `nornir_rows_fetched_per_job` | histogram | none | Training rows fetched per job. |
| `nornir_queue_depth` | gauge | none | Queued jobs seen on the last poll. |

## Völva

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `volva_predictions_served_total` | counter | none | Predictions published to Freki. |
| `volva_prediction_errors_total` | counter | `stage` (`row`, `extract`, `predict`, `publish`) | Inference failures, by stage. |
| `volva_inference_duration_seconds` | histogram | none | Time spent on each prediction. |
| `volva_active_model_age_seconds` | gauge | none | Seconds since the loaded model was created in Freki, or `0` when none is loaded. |
| `volva_active_model_id` | gauge | none | Id of the loaded model, or `0` when none is loaded. |
| `volva_csi_rows_consumed_total` | counter | none | Rows read from the CSI stream. |

Völva mounts `prometheus-fastapi-instrumentator` as well, but excludes its
only two handlers, `/health` and `/metrics`, from request metrics.

## Source of truth

- `geri/src/geri/metrics.py`
- `freki/src/freki/metrics.py`
- `nornir/src/nornir/metrics.py`
- `volva/src/volva/metrics.py`
