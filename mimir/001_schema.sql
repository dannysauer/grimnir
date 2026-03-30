-- =============================================================================
-- Grimnir — Database Schema (Mimir)
-- Requires: PostgreSQL 14+ with TimescaleDB extension
--
-- Install TimescaleDB first:
--   https://docs.timescale.com/self-hosted/latest/install/
--
-- Then run:
--   psql -U postgres -c "CREATE DATABASE csi;"
--   psql -U postgres -c "CREATE USER csi_user WITH PASSWORD 'changeme'; GRANT ALL ON DATABASE csi TO csi_user;"
--   psql -U postgres -d csi -f mimir/001_schema.sql
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- -----------------------------------------------------------------------------
-- Receivers
-- Represents each ESP32-S3 device. Supports up to 6 (1 tx + 5 rx).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS receivers (
    id          SERIAL PRIMARY KEY,
    mac         TEXT NOT NULL UNIQUE,       -- e.g. "aa:bb:cc:dd:ee:01"
    name        TEXT NOT NULL UNIQUE,       -- e.g. "rx_living_room"
    role        TEXT NOT NULL DEFAULT 'receiver'
                    CHECK (role IN ('transmitter', 'receiver')),
    floor       SMALLINT NOT NULL DEFAULT 0,
    location    TEXT,                       -- freeform: "NW corner, living room"
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed with initial 3 devices — update MACs after you flash your boards,
-- or let the aggregator (Geri) upsert the real MACs on first packet.
INSERT INTO receivers (mac, name, role, floor, location) VALUES
    ('00:00:00:00:00:01', 'tx_main',     'transmitter', 0, 'Ground floor, central'),
    ('00:00:00:00:00:02', 'rx_ground',   'receiver',    0, 'Ground floor, living area'),
    ('00:00:00:00:00:03', 'rx_upstairs', 'receiver',    1, 'Upper floor, hallway')
ON CONFLICT (mac) DO NOTHING;

-- -----------------------------------------------------------------------------
-- CSI Samples (hypertable — partitioned by time via TimescaleDB)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS csi_samples (
    time             TIMESTAMPTZ  NOT NULL,
    receiver_id      INTEGER      NOT NULL REFERENCES receivers(id),
    transmitter_mac  TEXT         NOT NULL,
    rssi             SMALLINT     NOT NULL,   -- dBm
    noise_floor      SMALLINT,                -- dBm, if available
    channel          SMALLINT     NOT NULL,
    bandwidth        SMALLINT     NOT NULL,   -- MHz: 20, 40, 80
    antenna_count    SMALLINT     NOT NULL DEFAULT 2,  -- ESP32-S3 has 2
    subcarrier_count SMALLINT     NOT NULL,
    -- CSI data as flat float arrays, length = antenna_count * subcarrier_count
    amplitude        REAL[]       NOT NULL,
    phase            REAL[]       NOT NULL,
    -- Raw packet bytes for reprocessing if parsing logic changes
    raw_bytes        BYTEA,
    label            TEXT         -- NULL until annotated; e.g. "kitchen", "empty"
);

-- Convert to TimescaleDB hypertable (7-day chunks)
SELECT create_hypertable(
    'csi_samples', 'time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_csi_receiver_time
    ON csi_samples (receiver_id, time DESC);

CREATE INDEX IF NOT EXISTS idx_csi_label
    ON csi_samples (label, time DESC)
    WHERE label IS NOT NULL;

-- TimescaleDB compression (kicks in after 7 days, ~90% space savings)
ALTER TABLE csi_samples SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'receiver_id',
    timescaledb.compress_orderby   = 'time DESC'
);

SELECT add_compression_policy('csi_samples', INTERVAL '7 days', if_not_exists => TRUE);

-- Continuous aggregate: per-minute stats per receiver (used by dashboard)
CREATE MATERIALIZED VIEW IF NOT EXISTS csi_variance_1min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', time)  AS bucket,
    receiver_id,
    COUNT(*)                        AS sample_count,
    AVG(rssi)                       AS avg_rssi,
    -- Scalar variance proxy: mean of per-sample amplitude variance
    AVG(
        (SELECT VARIANCE(v) FROM UNNEST(amplitude) AS v)
    )                               AS avg_amplitude_variance
FROM csi_samples
GROUP BY bucket, receiver_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('csi_variance_1min',
    start_offset      => INTERVAL '1 hour',
    end_offset        => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists     => TRUE
);

-- Retention: drop raw chunks older than 90 days
SELECT add_retention_policy('csi_samples', INTERVAL '90 days', if_not_exists => TRUE);

-- -----------------------------------------------------------------------------
-- Labels
-- Annotated time ranges for ML training data collection.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS labels (
    id          SERIAL PRIMARY KEY,
    time_start  TIMESTAMPTZ NOT NULL,
    time_end    TIMESTAMPTZ NOT NULL,
    room        TEXT        NOT NULL,  -- e.g. "kitchen", "office", "empty"
    occupants   SMALLINT    NOT NULL DEFAULT 1,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_range CHECK (time_end > time_start)
);

CREATE INDEX IF NOT EXISTS idx_labels_range
    ON labels USING GIST (tstzrange(time_start, time_end));

-- -----------------------------------------------------------------------------
-- Receiver heartbeats — track when each device last checked in
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS receiver_heartbeats (
    receiver_id      INTEGER     NOT NULL REFERENCES receivers(id),
    last_seen        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ip_address       INET,
    firmware_version TEXT,
    PRIMARY KEY (receiver_id)
);
