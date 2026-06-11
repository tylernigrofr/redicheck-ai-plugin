-- Migration 0010: incomplete-placeholder / unresolved-option-bracket residue (#61)
-- Captures unfinished MasterSpec boilerplate found in body text so the
-- project-level pass can emit one callout per page. Per-volume, page-anchored;
-- written by index_spec_pdf alongside spec_related_refs.

CREATE TABLE IF NOT EXISTS spec_placeholders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_id INTEGER NOT NULL REFERENCES spec_volumes(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('incomplete_placeholder', 'unresolved_option_bracket')),
    token TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_spec_placeholders_volume ON spec_placeholders(volume_id);
