-- Migration 0005: per-sheet discipline column (GitHub issue #32, ADR-0023)
--
ALTER TABLE drawing_sheets ADD COLUMN discipline TEXT;
