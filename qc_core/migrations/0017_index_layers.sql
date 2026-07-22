-- Migration 0017: per-layer index channels + discipline-index confirmation (issue #88)
--
-- ADR-0026 makes each discovered index layer its own Reconciliation Matrix
-- channel with layer-naming provenance (`master:1-G001`, `discipline:1-M000`).
-- No layer is ranked authoritative in code; which layer disagrees is a Claude
-- judgment across rows (CONTEXT.md Master Index / Discipline Index).
--
-- A Discipline Index is discovered by a deterministic candidate scan
-- (index-header / single-discipline density on the discipline's lead sheet)
-- and MUST be confirmed by a Claude page read before its channel is admitted:
-- a false channel would poison every matrix row set-wide. Until admitted, a
-- candidate layer's rows are Evidence only — the findings derived from them are
-- held at status='evidence' behind a tripped `discipline_index_unconfirmed`
-- invariant and never emit. Master layers (a general/cover-sheet index covering
-- a whole volume, or a set-wide cross-volume master) are auto-admitted.
--
-- confirmation_status persists across reindex (like ADR-0024 resolutions), so
-- an unchanged Drawing Set never re-asks the page-read question.
CREATE TABLE IF NOT EXISTS drawing_index_layers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_id INTEGER NOT NULL,
    layer_kind TEXT NOT NULL,              -- 'master' | 'discipline'
    provenance TEXT NOT NULL,              -- 'master:1-G001' | 'discipline:1-M000'
    lead_sheet_number TEXT,
    index_page INTEGER,
    discipline_prefix TEXT,                -- single dominant discipline (discipline layers)
    confirmation_status TEXT NOT NULL DEFAULT 'candidate'
        CHECK (confirmation_status IN ('candidate', 'admitted', 'rejected')),
    signals TEXT,
    rationale TEXT,
    UNIQUE (volume_id, provenance)
);

CREATE INDEX IF NOT EXISTS idx_index_layers_volume
    ON drawing_index_layers(volume_id);

-- Rebuild drawing_index_entries: add layer_provenance, and widen `source` (drop
-- the master_index/volume_index CHECK) so a building set can store the layer
-- provenance as the source discriminator, letting the same sheet number appear
-- in several layers (master + a discipline index) under the retained
-- UNIQUE(volume_id, sheet_number, source). Legacy non-building sets still write
-- 'master_index'/'volume_index' and keep NULL layer_provenance, unchanged.
CREATE TABLE drawing_index_entries_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_id INTEGER NOT NULL REFERENCES drawing_volumes(id) ON DELETE CASCADE,
    sheet_number TEXT NOT NULL,
    title TEXT,
    source TEXT NOT NULL,
    index_page INTEGER,
    layer_provenance TEXT,
    UNIQUE (volume_id, sheet_number, source)
);
INSERT INTO drawing_index_entries_new
    (id, volume_id, sheet_number, title, source, index_page)
    SELECT id, volume_id, sheet_number, title, source, index_page
    FROM drawing_index_entries;
DROP TABLE drawing_index_entries;
ALTER TABLE drawing_index_entries_new RENAME TO drawing_index_entries;
CREATE INDEX IF NOT EXISTS idx_drawing_index_entries_volume ON drawing_index_entries(volume_id);
CREATE INDEX IF NOT EXISTS idx_drawing_index_entries_number ON drawing_index_entries(sheet_number);
