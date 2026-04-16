-- Migration 004: rooms table and labels FK
--
-- Adds a dedicated rooms table so that room names are a controlled vocabulary
-- and labels.room can reference it with ON UPDATE CASCADE semantics (rename a
-- room and all its labels follow automatically).
--
-- Previously the rooms DDL was incorrectly included in migration 001, which
-- broke checksum validation on existing installs. This migration is the correct
-- home for that schema change.

-- -----------------------------------------------------------------------------
-- Rooms
-- Known rooms for location labeling. Name is the primary key so that FK
-- references in labels cascade automatically on rename (ON UPDATE CASCADE).
-- Future attributes (description, colour, etc.) can be added here.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rooms (
    name        TEXT        PRIMARY KEY,
    floor       SMALLINT    NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed common defaults — skipped if already present.
INSERT INTO rooms (name, floor) VALUES
    ('kitchen',     0),
    ('living_room', 0),
    ('hallway',     0),
    ('office',      1),
    ('bedroom',     1),
    ('empty',       0)
ON CONFLICT (name) DO NOTHING;

-- Populate rooms from any existing labels (floor 0 by default; edit via room
-- manager UI after the fact).  Must run after labels table is created.
INSERT INTO rooms (name)
SELECT DISTINCT room FROM labels
ON CONFLICT (name) DO NOTHING;

-- Add FK from labels.room → rooms.name with cascade-on-rename semantics.
-- Wrapped in a DO block so the migration is idempotent.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'labels_room_fkey'
    ) THEN
        ALTER TABLE labels
            ADD CONSTRAINT labels_room_fkey
            FOREIGN KEY (room) REFERENCES rooms(name)
            ON UPDATE CASCADE
            ON DELETE RESTRICT;
    END IF;
END $$;
