-- Migration 0003: from_label for refs in unnumbered sections (issue #12)
--
-- When a related-section ref appears on a page that the body extractor
-- couldn't anchor to a numbered CSI section (Division 00 forms, GPC
-- Invitation to Bid, etc.), we still want a stable identifier for the
-- containing section. from_label holds the nearest preceding PDF-outline
-- bookmark title.

ALTER TABLE spec_related_refs ADD COLUMN from_label TEXT;
ALTER TABLE findings ADD COLUMN from_label TEXT;
