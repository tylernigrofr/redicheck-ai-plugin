-- Migration 0018: suppressed-discipline discovery staging table (issue #100 ask 2)
--
-- Stores a discipline prefix the index text names with a real row run
-- (>= PREFIX_MIN_SHEETS on a single index page) that never survived to an
-- index channel AND has zero bookmarks in the same volume — the whole-
-- discipline-CNL class that would otherwise never produce a reconciliation
-- row at all (cf. #87's zero-volume warning, #71's per-prefix coverage
-- gate). Cleared and rebuilt on each index_drawing_pdf run for the volume,
-- like drawing_parse_anomalies / drawing_index_duplicates.

CREATE TABLE IF NOT EXISTS drawing_suppressed_discipline_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_id INTEGER NOT NULL REFERENCES drawing_volumes(id) ON DELETE CASCADE,
    prefix TEXT NOT NULL,
    index_page INTEGER,
    row_count INTEGER NOT NULL,
    sample TEXT
);

CREATE INDEX IF NOT EXISTS idx_suppressed_discipline_volume
    ON drawing_suppressed_discipline_candidates(volume_id);
