-- =============================================================================
-- Grimnir — Migration 008: shared current prediction state
-- =============================================================================
-- Stores the latest prediction envelope in Postgres so every Freki replica sees
-- the same current state and SSE streams can poll a shared source of truth.
-- =============================================================================

CREATE TABLE IF NOT EXISTS current_predictions (
    id         SMALLINT    PRIMARY KEY CHECK (id = 1),
    payload    JSONB       NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
