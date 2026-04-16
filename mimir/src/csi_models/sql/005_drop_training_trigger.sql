-- Migration 005: replace row-level training_samples trigger with bulk sync
--
-- The row-level trigger trg_sync_training_sample fired once per updated row in
-- csi_samples. Labeling a 5-minute window (~11k rows) caused ~11k individual
-- INSERTs into training_samples within one transaction, timing out asyncpg.
--
-- The trigger is dropped here; the application layer (create_label /
-- delete_label in freki) now performs the sync as a single bulk INSERT/DELETE.

DROP TRIGGER IF EXISTS trg_sync_training_sample ON csi_samples;
DROP FUNCTION IF EXISTS sync_training_sample();
