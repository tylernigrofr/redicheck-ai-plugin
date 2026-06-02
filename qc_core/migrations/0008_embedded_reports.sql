-- Migration 0008: embedded non-CSI reports bound into a spec set (#43)
--
-- Reports like a Geotechnical Engineering Report are listed in the spec TOC but
-- have no SECTION NN NN NN body header, so the TOC<->body diff flags them as a
-- false toc_not_in_body. The PDF outline confirms presence (a bookmark for the
-- number whose subtree carries its own Table of Contents). We persist the
-- confirmed-present reports per volume so compute_project_findings can downgrade
-- the corresponding toc_not_in_body to an informational note.
--
-- Rebuilt wholesale on every index pass, like spec_sections.

CREATE TABLE IF NOT EXISTS embedded_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_id INTEGER NOT NULL REFERENCES spec_volumes(id) ON DELETE CASCADE,
    number TEXT NOT NULL,
    title TEXT,
    page INTEGER,
    UNIQUE (volume_id, number)
);

CREATE INDEX IF NOT EXISTS idx_embedded_reports_volume ON embedded_reports(volume_id);
CREATE INDEX IF NOT EXISTS idx_embedded_reports_number ON embedded_reports(number);
