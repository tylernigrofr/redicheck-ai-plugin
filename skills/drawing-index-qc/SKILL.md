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
drawing-index-qc <project-folder> --mode=matrix
drawing-index-qc <project-folder> --apply-judgments decisions.json
drawing-index-qc <project-folder> --mode=emit --reviewer "Your Name"
drawing-index-qc <project-folder> --mode=emit --kind sheet_in_index_not_in_set
```

Reviewer resolution: `--reviewer` > `qc.config.toml [reviewer] name` > built-in
default `REDICHECK-TKN`. `--kind` (repeatable) restricts emit to the given
finding kind(s); omit it to emit every markup-eligible kind.

Default `--mode=preview`. The flip to `emit` is deferred — see [precision-thresholds.md](../../docs/precision-thresholds.md) (Default-flip status, drawing-index-qc) for the 2026-05-21 baseline and the conditions for revisit.

## Behavior

- Auto-runs `qc-index` when `qc.sqlite` is missing or stale (spec or drawing PDFs).
- **preview**: prints drawing findings grouped by `kind` from `qc.sqlite`. Shows an UNTRUSTED SCOPE banner when invariants are tripped or Evidence is pending.
- **matrix**: prints the judgment-node worklist as JSON — tripped invariants, findings at `status=evidence`, and disputed reconciliation-matrix rows (ADR-0026).
- **emit**: writes one red Revu-style FreeText callout per finding via PyMuPDF (ADR-0012) — the same markup style as spec-check (`qc_core.markup`). Reviewer falls back to `qc.config.toml [reviewer] name`, else the built-in default `REDICHECK-TKN`. Default output is `<name>.marked.pdf`; pass `--in-place` to overwrite sources. **Exits 2 without writing** when any invariant is tripped or any Evidence is unjudged — you cannot sign off on a list with known completeness gaps (ADR-0026 §6a).

## Harness loop (ADR-0026)

This skill is the deterministic harness; you (Claude) fill the judgment nodes. The loop shape is fixed — do not free-drive it:

1. Run `drawing-index-qc <project> --mode=matrix`.
2. If `invariants` has tripped rows or `pending_evidence` is non-empty, **judge each disputed item**. For every tripped invariant, open the source PDF page(s) in the `detail` (e.g. via `qc_core` helpers or `PyMuPDF`) and determine what actually happened: real omission, parse gap, sub-project set, parse noise. For every `pending_evidence` finding, decide using its matrix row (`disputed_rows`).
3. Write a decisions file and apply it: `drawing-index-qc <project> --apply-judgments decisions.json`. Schema:

   ```json
   {
     "decisions": [
       {"evidence_key": "S4.1", "action": "promote|dismiss|reclassify",
        "kind": "<required for reclassify>",
        "rationale": "one line, grounded in what you read on the page"}
     ],
     "invariants": [
       {"id": 3, "status": "resolved", "rationale": "what the investigation found"}
     ]
   }
   ```

   `resolved` = you investigated and judged; `overridden` = the Reviewer made the call (ADR-0024 Resolution). Never resolve an invariant without reading the page it points at; never dismiss Evidence without a rationale. If a parse gap is the cause, the dismissal rationale is the labeled example that improves discovery later — be specific.
4. Re-run `--mode=preview`; when the UNTRUSTED banner is gone, proceed to triage/emit as usual.

Judgments persist in `qc.sqlite` — re-runs on an unchanged Drawing Set do not re-ask.

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
