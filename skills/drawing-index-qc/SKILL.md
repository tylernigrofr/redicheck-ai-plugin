---
name: drawing-index-qc
description: >
  QC-checks construction drawing indexes against PDF drawing sets. Indexes via
  qc-index, previews findings from qc.sqlite. Per ADR-0010 and ADR-0014.
---

# /drawing-index-qc

Drawing Index QC for RediCheck — cross-reference sheet indexes with title blocks
in the Drawing Set.

## Usage

```bash
qc-index <project-folder>
drawing-index-qc <project-folder> --mode=preview
drawing-index-qc <project-folder> --mode=emit --reviewer "Your Name"
drawing-index-qc <project-folder> --mode=emit --kind sheet_in_index_not_in_set
```

Reviewer resolution: `--reviewer` > `qc.config.toml [reviewer] name` > built-in
default `REDICHECK-TKN`. `--kind` (repeatable) restricts emit to the given
finding kind(s); omit it to emit every markup-eligible kind.

Default `--mode=preview`. The flip to `emit` is deferred — see [precision-thresholds.md](../../docs/precision-thresholds.md) (Default-flip status, drawing-index-qc) for the 2026-05-21 baseline and the conditions for revisit.

## Behavior

- Auto-runs `qc-index` when `qc.sqlite` is missing or stale (spec or drawing PDFs).
- **preview**: prints drawing findings grouped by `kind` from `qc.sqlite`.
- **emit**: writes one red Revu-style FreeText callout per finding via PyMuPDF (ADR-0012) — the same markup style as spec-check (`qc_core.markup`). Reviewer falls back to `qc.config.toml [reviewer] name`, else the built-in default `REDICHECK-TKN`. Default output is `<name>.marked.pdf`; pass `--in-place` to overwrite sources.

## Emit conventions (ADR-0012)

- **Markup** = red, bold FreeText callout, Bluebeam-Revu-native rich text, placed next to the sheet number on the page.
- **Author** = configured Reviewer (`/T`), not Assistant.
- **Subject** = `drawing-index-qc:<kind>` (kebab-case kind slug).
- **Comments** = one-line explanation; sheet number; source page.
- **Idempotency**: re-run deletes prior `drawing-index-qc:` markups and rewrites them — no duplication.

## Extraction (ADR-0014)

- **Sheet catalog**: PDF bookmarks at outline depth 2 (`<SHEET_NUMBER> - <TITLE>`).
- **Sheet index**: vector text on pages matching index headers in the first 15 pages.
- **Cross-check**: title-block text vs bookmark (only when `[drawing.title_block] calibrated = true` in `qc.config.toml`).

## Finding kinds

- `sheet_in_index_not_in_set` — CNL: indexed but not in PDF set
- `sheet_in_set_not_in_index` — UNLISTED: in PDF but not in index
- `sheet_number_mismatch` — AVW: bookmark vs title block (when calibrated)
- `duplicate_sheet_number` — IR: duplicate row in an index

## Related ADRs

- [ADR-0010](../../docs/adr/0010-foundation-first-spec-and-drawing-index-as-qc-core-v0.md)
- [ADR-0014](../../docs/adr/0014-drawing-index-extraction-via-bookmarks-with-titleblock-crosscheck.md)
- [ADR-0012](../../docs/adr/0012-pymupdf-direct-annotation-emit-supersedes-mcp-for-mass-markups.md)
- [ADR-0007](../../docs/adr/0007-testing-with-curated-expected-outputs-per-project.md)

## Issue filing reflex

If this skill exits non-zero, throws, or the Reviewer says a finding is wrong or missing, offer `/report-issue` (see `/help`).

## Legacy reference

Prior workflow: `legacy/skills/drawing-index-qc/`
