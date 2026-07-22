-- Migration 0016: building-namespace prefix on sheets (GitHub issue #86)
--
-- Building-prefixed sheet numbers ("16-S101", "2-A101") namespace a shared
-- discipline number across per-building volumes. The full namespaced key is
-- stored in drawing_sheets.sheet_number; this column exposes the parsed
-- building segment ("16") on its own so downstream consumers (#89/#90/#93)
-- read the namespace without re-parsing the key. NULL for non-prefixed sheets.
ALTER TABLE drawing_sheets ADD COLUMN building_prefix TEXT;
