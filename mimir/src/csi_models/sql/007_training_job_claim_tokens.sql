-- =============================================================================
-- Grimnir — Migration 007: training job claim tokens
-- =============================================================================
-- Adds an opaque claim token to running jobs so only the daemon that claimed
-- the job can heartbeat it, mark it complete, or fail it.
-- =============================================================================

ALTER TABLE training_jobs
    ADD COLUMN IF NOT EXISTS claim_token TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_training_jobs_claim_token
    ON training_jobs (claim_token)
    WHERE claim_token IS NOT NULL;
