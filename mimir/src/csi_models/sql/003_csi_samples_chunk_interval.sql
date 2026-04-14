-- Migration 003: tighten csi_samples chunk interval and compression lag
--
-- Previously csi_samples used the default 7-day chunk interval, which meant
-- compress_after='2 days' was dominated by the chunk size (data wasn't eligible
-- for compression until ~9 days old).  Switch to 2-day chunks so compression
-- kicks in ~4 days after data is recorded, while still giving a comfortable
-- window for labeling data from the past day or two.

SELECT set_chunk_time_interval('csi_samples', INTERVAL '2 days');

SELECT remove_compression_policy('csi_samples');
SELECT add_compression_policy('csi_samples', compress_after => INTERVAL '2 days');
