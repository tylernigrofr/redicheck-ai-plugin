-- Migration 0006: door schedule discovery, resolution, and extraction (GitHub issue #33)

CREATE TABLE IF NOT EXISTS door_schedule_regions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sheet_number TEXT NOT NULL,
    page INTEGER NOT NULL,
    bbox_x0 REAL NOT NULL,
    bbox_y0 REAL NOT NULL,
    bbox_x1 REAL NOT NULL,
    bbox_y1 REAL NOT NULL,
    sub_schedule_name TEXT,
    source TEXT NOT NULL DEFAULT 'auto'
        CHECK (source IN ('auto', 'reviewer')),
    resolved_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (sheet_number, bbox_x0, bbox_y0, bbox_x1, bbox_y1, sub_schedule_name)
);

CREATE TABLE IF NOT EXISTS door_column_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_label TEXT NOT NULL,
    canonical_field TEXT NOT NULL,
    UNIQUE (raw_label, canonical_field)
);

CREATE TABLE IF NOT EXISTS doors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    door_no TEXT NOT NULL,
    width TEXT,
    height TEXT,
    door_material TEXT,
    frame_material TEXT,
    fire_rating TEXT,
    hardware_set TEXT,
    attributes TEXT NOT NULL DEFAULT '{}',
    source_sheet TEXT NOT NULL,
    source_page INTEGER NOT NULL,
    source_bbox_x0 REAL,
    source_bbox_y0 REAL,
    source_bbox_x1 REAL,
    source_bbox_y1 REAL,
    sub_schedule_name TEXT,
    region_id INTEGER REFERENCES door_schedule_regions(id) ON DELETE SET NULL,
    extracted_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_doors_door_no ON doors(door_no);
CREATE INDEX IF NOT EXISTS idx_doors_source_sheet ON doors(source_sheet);
CREATE INDEX IF NOT EXISTS idx_door_regions_sheet ON door_schedule_regions(sheet_number);
