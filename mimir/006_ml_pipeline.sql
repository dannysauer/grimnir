-- =============================================================================
-- Grimnir — Migration 006: ML training pipeline schema
-- =============================================================================
-- Adds three tables:
--   training_daemons  — Nornir instance registry (mirrors receivers/heartbeats)
--   training_jobs     — job queue with status lifecycle
--   trained_models    — model registry with inline BYTEA storage
--
-- See issues #16, #17, #18, #19.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Training daemons
-- One row per Nornir instance that can train models. Upserted on each heartbeat.
-- Matches the receivers/receiver_heartbeats pattern but folded into one table
-- since daemons are cattle — no persistent metadata beyond name.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS training_daemons (
    id           SERIAL      PRIMARY KEY,
    name         TEXT        NOT NULL UNIQUE,
    host         TEXT        NOT NULL,
    ip_address   INET,
    capabilities JSONB       NOT NULL DEFAULT '{}'::jsonb,
    last_seen    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- capabilities shape:
--   {
--     "gpu": [{"name": "Tesla P100", "vram_mb": 16384}, ...],
--     "cpu": {"model": "...", "cores": 8}
--   }

-- -----------------------------------------------------------------------------
-- Training jobs
-- Status lifecycle: queued → running → complete / failed / cancelled.
-- `spec` carries model_type, hyperparams, feature_config, time window, rooms.
-- `heartbeat_at` is bumped by the daemon during training so Freki can reap
-- orphans whose daemons crashed mid-job.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS training_jobs (
    id           SERIAL      PRIMARY KEY,
    status       TEXT        NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued', 'running', 'failed', 'complete', 'cancelled')),
    spec         JSONB       NOT NULL,
    daemon_id    INTEGER     REFERENCES training_daemons(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at   TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error        TEXT
);

-- Two indexes cover the hot paths: daemons polling for queued jobs, and the
-- orphan reaper scanning running jobs with stale heartbeats.
CREATE INDEX IF NOT EXISTS idx_training_jobs_status_created
    ON training_jobs (status, created_at);

CREATE INDEX IF NOT EXISTS idx_training_jobs_running_heartbeat
    ON training_jobs (heartbeat_at)
    WHERE status = 'running';

-- -----------------------------------------------------------------------------
-- Trained models
-- Inline BYTEA storage (TOAST handles the large blobs). Partial unique index
-- enforces "at most one active model" without sweeping every row on activate.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trained_models (
    id              SERIAL      PRIMARY KEY,
    name            TEXT        NOT NULL,
    training_job_id INTEGER     REFERENCES training_jobs(id) ON DELETE SET NULL,
    is_active       BOOLEAN     NOT NULL DEFAULT FALSE,
    metrics         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    feature_config  JSONB       NOT NULL DEFAULT '{}'::jsonb,
    model_data      BYTEA       NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- metrics shape:
--   {
--     "accuracy": 0.87,
--     "confusion_matrix": [[...], ...],
--     "n_samples": 4200,
--     "train_start": "...", "train_end": "...",
--     "rooms": ["kitchen", ...]
--   }
--
-- feature_config shape: see csi_models.features.FeatureConfig. Always carries
-- a `version` int so Völva can refuse models whose extractor doesn't match.

CREATE UNIQUE INDEX IF NOT EXISTS trained_models_one_active
    ON trained_models (is_active) WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_trained_models_created
    ON trained_models (created_at DESC);
