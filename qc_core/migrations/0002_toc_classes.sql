-- Migration 0002: TOC equivalence classes for multi-volume specs (ADR-0013)

CREATE TABLE IF NOT EXISTS toc_classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    section_count INTEGER NOT NULL,
    representative_volume_id INTEGER REFERENCES spec_volumes(id) ON DELETE SET NULL
);

ALTER TABLE spec_volumes ADD COLUMN toc_class_id INTEGER REFERENCES toc_classes(id);

CREATE TABLE IF NOT EXISTS toc_class_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    toc_class_id INTEGER NOT NULL REFERENCES toc_classes(id) ON DELETE CASCADE,
    number TEXT NOT NULL,
    title TEXT,
    toc_page INTEGER,
    UNIQUE (toc_class_id, number)
);

CREATE INDEX IF NOT EXISTS idx_toc_class_sections_class ON toc_class_sections(toc_class_id);
CREATE INDEX IF NOT EXISTS idx_toc_class_sections_number ON toc_class_sections(number);
CREATE INDEX IF NOT EXISTS idx_spec_volumes_toc_class ON spec_volumes(toc_class_id);

-- Migrate any existing toc rows in spec_sections into singleton classes.
-- Each pre-existing volume becomes its own 1-member class.
INSERT INTO toc_classes (fingerprint, section_count, representative_volume_id)
SELECT
    'legacy-singleton-vol-' || volume_id AS fingerprint,
    COUNT(*) AS section_count,
    volume_id AS representative_volume_id
FROM spec_sections
WHERE source = 'toc'
GROUP BY volume_id;

UPDATE spec_volumes
SET toc_class_id = (
    SELECT id FROM toc_classes
    WHERE representative_volume_id = spec_volumes.id
)
WHERE EXISTS (
    SELECT 1 FROM toc_classes
    WHERE representative_volume_id = spec_volumes.id
);

INSERT INTO toc_class_sections (toc_class_id, number, title, toc_page)
SELECT sv.toc_class_id, ss.number, ss.title, ss.toc_page
FROM spec_sections ss
JOIN spec_volumes sv ON sv.id = ss.volume_id
WHERE ss.source = 'toc' AND sv.toc_class_id IS NOT NULL;

DELETE FROM spec_sections WHERE source = 'toc';
