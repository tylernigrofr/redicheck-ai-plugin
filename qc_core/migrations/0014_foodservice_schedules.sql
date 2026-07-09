-- Migration 0014: foodservice utility schedule vs electrical kitchen equipment
-- schedule extraction and cross-check (Food Service vs Electrical, Aman Aspen).
--
-- Both schedules are rotated 90 degrees on the sheet: items run along x,
-- attributes along y. We extract the electrical-relevant columns from each
-- side and store them so future checks (e.g. Food Service vs Plumbing) can
-- reuse the same foodservice item rows.

CREATE TABLE IF NOT EXISTS fs_equipment_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_number TEXT NOT NULL,
    qty TEXT,
    description TEXT,
    volts TEXT,
    ph TEXT,
    amps TEXT,
    kw TEXT,
    hz TEXT,
    elec_conn_type TEXT,
    elec_rough_in_aff TEXT,
    attributes TEXT NOT NULL DEFAULT '{}',
    source_sheet TEXT NOT NULL,
    source_page INTEGER NOT NULL,
    source_bbox_x0 REAL,
    source_bbox_y0 REAL,
    source_bbox_x1 REAL,
    source_bbox_y1 REAL,
    extracted_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS elec_kitchen_marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mark TEXT NOT NULL,
    base_item TEXT,            -- mark with unit suffix stripped (A6.1 -> A6)
    description TEXT,
    volt TEXT,
    phase TEXT,
    watts TEXT,
    amps TEXT,
    connection TEXT,           -- 'hardwired' | 'receptacle' | NULL
    disconnect TEXT,
    height TEXT,
    attributes TEXT NOT NULL DEFAULT '{}',
    source_sheet TEXT NOT NULL,
    source_page INTEGER NOT NULL,
    source_bbox_x0 REAL,
    source_bbox_y0 REAL,
    source_bbox_x1 REAL,
    source_bbox_y1 REAL,
    extracted_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_fs_items_number ON fs_equipment_items(item_number);
CREATE INDEX IF NOT EXISTS idx_elec_marks_mark ON elec_kitchen_marks(mark);
CREATE INDEX IF NOT EXISTS idx_elec_marks_base ON elec_kitchen_marks(base_item);
