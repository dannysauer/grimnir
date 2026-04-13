-- =============================================================================
-- Grimnir — Migration 002: training_samples + tighter retention/compression
-- =============================================================================

-- ── Tighten compression and retention on csi_samples ─────────────────────

-- Compress after 2 days (unlabeled data loses most value quickly)
SELECT remove_compression_policy('csi_samples', if_exists => TRUE);
SELECT add_compression_policy('csi_samples', INTERVAL '2 days', if_not_exists => TRUE);

-- Retain 14 days of raw data (enough for retroactive labeling)
SELECT remove_retention_policy('csi_samples', if_exists => TRUE);
SELECT add_retention_policy('csi_samples', INTERVAL '14 days', if_not_exists => TRUE);

-- ── Long-term labeled training data ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS training_samples (
    time             TIMESTAMPTZ  NOT NULL,
    receiver_id      INTEGER      NOT NULL REFERENCES receivers(id),
    transmitter_mac  TEXT         NOT NULL,
    rssi             SMALLINT     NOT NULL,
    noise_floor      SMALLINT,
    channel          SMALLINT     NOT NULL,
    bandwidth        SMALLINT     NOT NULL,
    antenna_count    SMALLINT     NOT NULL DEFAULT 2,
    subcarrier_count SMALLINT     NOT NULL,
    amplitude        REAL[]       NOT NULL,
    phase            REAL[]       NOT NULL,
    raw_bytes        BYTEA,
    label            TEXT         NOT NULL  -- always labeled; sync trigger enforces this
);

SELECT create_hypertable(
    'training_samples', 'time',
    chunk_time_interval => INTERVAL '90 days',  -- sparse writes, large chunks
    if_not_exists => TRUE
);

-- Unique index to support upsert from trigger (relabeling a window)
CREATE UNIQUE INDEX IF NOT EXISTS idx_training_samples_time_receiver
    ON training_samples (time, receiver_id);

CREATE INDEX IF NOT EXISTS idx_training_samples_label_time
    ON training_samples (label, time DESC);

ALTER TABLE training_samples SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'receiver_id',
    timescaledb.compress_orderby   = 'time DESC'
);
SELECT add_compression_policy('training_samples', INTERVAL '30 days', if_not_exists => TRUE);

-- No retention policy — labeled data is kept indefinitely.

-- ── Trigger: sync labeled rows from csi_samples → training_samples ────────

CREATE OR REPLACE FUNCTION sync_training_sample() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.label IS NOT NULL THEN
        -- Label set or changed: upsert into training set
        INSERT INTO training_samples (
            time, receiver_id, transmitter_mac, rssi, noise_floor,
            channel, bandwidth, antenna_count, subcarrier_count,
            amplitude, phase, raw_bytes, label
        ) VALUES (
            NEW.time, NEW.receiver_id, NEW.transmitter_mac, NEW.rssi, NEW.noise_floor,
            NEW.channel, NEW.bandwidth, NEW.antenna_count, NEW.subcarrier_count,
            NEW.amplitude, NEW.phase, NEW.raw_bytes, NEW.label
        )
        ON CONFLICT (time, receiver_id)
        DO UPDATE SET label = EXCLUDED.label;
    ELSE
        -- Label cleared: remove from training set
        DELETE FROM training_samples
        WHERE time = OLD.time AND receiver_id = OLD.receiver_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sync_training_sample
    AFTER UPDATE OF label ON csi_samples
    FOR EACH ROW
    WHEN (OLD.label IS DISTINCT FROM NEW.label)
    EXECUTE FUNCTION sync_training_sample();
