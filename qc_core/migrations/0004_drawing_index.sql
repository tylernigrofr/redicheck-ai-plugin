-- Migration 0004: drawing index foundation tables (ADR-0010, issue #14)
--
-- Substrate for Drawing Index QC. Extraction and findings population come in
-- later slices; kinds reserved here for drawing-index findings.

CREATE TABLE IF NOT EXISTS drawing_volumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pdf_path TEXT NOT NULL UNIQUE,
    pdf_mtime REAL NOT NULL,
    page_count INTEGER,
    discipline TEXT,
    set_pattern TEXT NOT NULL DEFAULT 'single_discipline'
        CHECK (set_pattern IN ('single_discipline', 'bundled_set')),
    indexed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS drawing_index_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_id INTEGER NOT NULL REFERENCES drawing_volumes(id) ON DELETE CASCADE,
    sheet_number TEXT NOT NULL,
    title TEXT,
    source TEXT NOT NULL CHECK (source IN ('master_index', 'volume_index')),
    index_page INTEGER,
    UNIQUE (volume_id, sheet_number, source)
);

CREATE TABLE IF NOT EXISTS drawing_sheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_id INTEGER NOT NULL REFERENCES drawing_volumes(id) ON DELETE CASCADE,
    sheet_number TEXT NOT NULL,
    title TEXT,
    page INTEGER NOT NULL,
    confidence TEXT,
    UNIQUE (volume_id, sheet_number, page)
);

CREATE INDEX IF NOT EXISTS idx_drawing_volumes_path ON drawing_volumes(pdf_path);
CREATE INDEX IF NOT EXISTS idx_drawing_index_entries_volume ON drawing_index_entries(volume_id);
CREATE INDEX IF NOT EXISTS idx_drawing_index_entries_number ON drawing_index_entries(sheet_number);
CREATE INDEX IF NOT EXISTS idx_drawing_sheets_volume ON drawing_sheets(volume_id);
CREATE INDEX IF NOT EXISTS idx_drawing_sheets_number ON drawing_sheets(sheet_number);

ALTER TABLE findings ADD COLUMN drawing_volume_id INTEGER
    REFERENCES drawing_volumes(id) ON DELETE CASCADE;
ALTER TABLE findings ADD COLUMN sheet_number TEXT;

CREATE INDEX IF NOT EXISTS idx_findings_drawing_volume ON findings(drawing_volume_id);
