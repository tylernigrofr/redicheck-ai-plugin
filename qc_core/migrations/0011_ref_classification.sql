-- #59: classify broken_related_ref into CNL / IR / suffix / typo / dedup.
-- link_text: the section title adjacent to a cross-reference in the prose
-- ("Section 05 51 13, Metal Stairs" -> "Metal Stairs"), captured at index
-- time so the IR classifier can fuzzy-match it against the section index.
ALTER TABLE spec_related_refs ADD COLUMN link_text TEXT;

-- ref_class on findings: comma-separated tags driving emit wording for
-- broken_related_ref ('ir' | 'suffix' | 'digit_typo', optionally ',typical'
-- when volume-wide dedup collapsed repeat refs onto this first occurrence).
ALTER TABLE findings ADD COLUMN ref_class TEXT;
