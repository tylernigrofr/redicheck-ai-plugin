-- Migration 0012: drawing parse-anomaly staging table (ADR-0027 / issue #65)
--
-- Stores raw extraction failures from each channel before they are promoted to
-- findings rows.  parse_anomaly findings in the findings table reference back
-- to these rows via notes=raw_text.  Cleared and rebuilt on each index_drawing_pdf
-- run for the volume (like drawing_sheets / drawing_index_entries).

CREATE TABLE IF NOT EXISTS drawing_parse_anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_id INTEGER NOT NULL REFERENCES drawing_volumes(id) ON DELETE CASCADE,
    channel TEXT NOT NULL CHECK (channel IN ('bookmarks', 'volume_index', 'master_index')),
    raw_text TEXT NOT NULL,
    page INTEGER,
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_parse_anomalies_volume
    ON drawing_parse_anomalies(volume_id);
