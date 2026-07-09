-- Migration 0013: per-volume extraction-blindness signal (issue #75)
--
-- JSON payload written by index_drawing_pdf recording per-page char counts,
-- whether an index header was found, and how many index rows parsed.  Read by
-- evaluate_invariants to distinguish "index absent" (prefix_absent_from_index)
-- from "index exists but is raster/flattened" (index_unreadable).

ALTER TABLE drawing_volumes ADD COLUMN extraction_signal TEXT;
