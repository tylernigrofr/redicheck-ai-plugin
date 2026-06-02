-- Migration 0007: allow duplicate CSI section numbers (#45)
--
-- A spec can legitimately reuse the same section number for two different
-- sections (a coordination defect we must surface). The old one-row-per-number
-- uniqueness silently dropped the second occurrence, so the duplicate was
-- invisible. Add an `occurrence` discriminator to spec_sections and
-- toc_class_sections and widen their uniqueness to include it.
--
-- Both tables are rebuilt wholesale on every index pass, so existing rows just
-- need to carry occurrence = 1 forward.

-- spec_sections (body rows only post-0002) ---------------------------------
CREATE TABLE spec_sections_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_id INTEGER NOT NULL REFERENCES spec_volumes(id) ON DELETE CASCADE,
    number TEXT NOT NULL,
    title TEXT,
    source TEXT NOT NULL CHECK (source IN ('toc', 'body')),
    page INTEGER,
    toc_page INTEGER,
    occurrence INTEGER NOT NULL DEFAULT 1,
    UNIQUE (volume_id, number, source, occurrence)
);

INSERT INTO spec_sections_new (id, volume_id, number, title, source, page, toc_page, occurrence)
SELECT id, volume_id, number, title, source, page, toc_page, 1
FROM spec_sections;

DROP TABLE spec_sections;
ALTER TABLE spec_sections_new RENAME TO spec_sections;

CREATE INDEX IF NOT EXISTS idx_spec_sections_volume ON spec_sections(volume_id);
CREATE INDEX IF NOT EXISTS idx_spec_sections_number ON spec_sections(number);

-- toc_class_sections -------------------------------------------------------
CREATE TABLE toc_class_sections_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    toc_class_id INTEGER NOT NULL REFERENCES toc_classes(id) ON DELETE CASCADE,
    number TEXT NOT NULL,
    title TEXT,
    toc_page INTEGER,
    occurrence INTEGER NOT NULL DEFAULT 1,
    UNIQUE (toc_class_id, number, occurrence)
);

INSERT INTO toc_class_sections_new (id, toc_class_id, number, title, toc_page, occurrence)
SELECT id, toc_class_id, number, title, toc_page, 1
FROM toc_class_sections;

DROP TABLE toc_class_sections;
ALTER TABLE toc_class_sections_new RENAME TO toc_class_sections;

CREATE INDEX IF NOT EXISTS idx_toc_class_sections_class ON toc_class_sections(toc_class_id);
CREATE INDEX IF NOT EXISTS idx_toc_class_sections_number ON toc_class_sections(number);
