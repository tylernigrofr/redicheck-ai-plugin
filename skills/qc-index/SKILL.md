---
name: qc-index
description: Discover spec PDFs in a project folder, run the Spec Indexer, and write qc.sqlite next to the PDFs. Per ADR-0010 and ADR-0004.
---

# /qc-index

Index specification and drawing PDFs into the project's `qc.sqlite` substrate.

## Usage

```bash
qc-index <project-folder>
qc-index <project-folder> --force
```

## Behavior

- Discovers spec PDFs via filename heuristics (`Specs.pdf`, `Specifications.pdf`, etc.)
- Discovers drawing PDFs (bundled `Drawings.pdf`, per-discipline PDFs, numbered volumes)
- Runs `qc_core.spec.indexer` and `qc_core.drawing.indexer` (ADR-0014)
- Writes spec tables, `drawing_volumes`, `drawing_sheets`, `drawing_index_entries`, and findings
- Skips re-index when PDF mtime unchanged (ADR-0010)

## Related ADRs

- ADR-0004 — local-first `qc.sqlite`
- ADR-0005 — generalization via config knobs
- ADR-0010 — foundation-first spec index

## Issue filing reflex

If this skill exits non-zero, throws, or the Reviewer says indexing missed expected content, offer `/report-issue` (see `/help`).
