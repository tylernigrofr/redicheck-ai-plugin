-- Migration 0015: drawing index-channel duplicate staging table (issue #76)
--
-- Stores sheet numbers listed MORE THAN ONCE within a single index page's
-- table (a real intra-region duplicate row) before compute_drawing_findings
-- promotes them to duplicate_sheet_number findings. Cleared and rebuilt on
-- each index_drawing_pdf run for the volume (like drawing_parse_anomalies).

CREATE TABLE IF NOT EXISTS drawing_index_duplicates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_id INTEGER NOT NULL REFERENCES drawing_volumes(id) ON DELETE CASCADE,
    sheet_number TEXT NOT NULL,
    title TEXT,
    count INTEGER NOT NULL,
    page INTEGER,
    source TEXT
);

CREATE INDEX IF NOT EXISTS idx_index_duplicates_volume
    ON drawing_index_duplicates(volume_id);
