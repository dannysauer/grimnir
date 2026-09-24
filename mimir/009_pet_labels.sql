-- Migration 009: pet_count on labels
--
-- Adds a dedicated pet_count column so pets can be tracked separately from
-- the human occupant count. `occupants` remains the human-count field used
-- as the v1 ML training target (see #14) — going forward it should be
-- entered as humans only, with pets recorded via pet_count instead.
-- Historical rows default to pet_count = 0 since existing `occupants`
-- values cannot be retroactively split.

ALTER TABLE labels
    ADD COLUMN IF NOT EXISTS pet_count SMALLINT NOT NULL DEFAULT 0;
