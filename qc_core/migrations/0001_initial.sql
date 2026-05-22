-- Migration 0001: spec index foundation tables (ADR-0004, ADR-0010)

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS spec_volumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pdf_path TEXT NOT NULL UNIQUE,
    pdf_mtime REAL NOT NULL,
    page_count INTEGER,
    toc_start INTEGER,
    toc_end INTEGER,
    body_start INTEGER,
    has_full_toc INTEGER NOT NULL DEFAULT 1,
    indexed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS spec_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_id INTEGER NOT NULL REFERENCES spec_volumes(id) ON DELETE CASCADE,
    number TEXT NOT NULL,
    title TEXT,
    source TEXT NOT NULL CHECK (source IN ('toc', 'body')),
    page INTEGER,
    toc_page INTEGER,
    UNIQUE (volume_id, number, source)
);

CREATE TABLE IF NOT EXISTS spec_related_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_id INTEGER NOT NULL REFERENCES spec_volumes(id) ON DELETE CASCADE,
    from_section TEXT,
    referenced_number TEXT NOT NULL,
    context_line TEXT,
    page INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_spec_sections_volume ON spec_sections(volume_id);
CREATE INDEX IF NOT EXISTS idx_spec_sections_number ON spec_sections(number);
CREATE INDEX IF NOT EXISTS idx_spec_related_refs_volume ON spec_related_refs(volume_id);
CREATE INDEX IF NOT EXISTS idx_spec_related_refs_target ON spec_related_refs(referenced_number);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_id INTEGER REFERENCES spec_volumes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    expected_action TEXT NOT NULL DEFAULT 'emit_markup'
        CHECK (expected_action IN ('emit_markup', 'info_only', 'suppress')),
    severity TEXT,
    section TEXT,
    title TEXT,
    from_section TEXT,
    to_section TEXT,
    source_page INTEGER,
    body_page INTEGER,
    toc_page INTEGER,
    division TEXT,
    client_comment TEXT,
    probable_match TEXT,
    context TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_findings_kind ON findings(kind);
CREATE INDEX IF NOT EXISTS idx_findings_action ON findings(expected_action);
