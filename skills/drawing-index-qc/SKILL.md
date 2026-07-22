---
name: drawing-index-qc
description: >
  QC-checks construction drawing indexes against PDF drawing sets. Indexes via
  qc-index, previews findings from qc.sqlite. Per ADR-0010 and ADR-0014.
---

# /drawing-index-qc

Drawing Index QC for RediCheck — cross-reference sheet indexes with title blocks
in the Drawing Set.

## The tool is decision support, not the verdict

The findings list is a **lead generator** — a fast way to surface candidates so
you don't read every sheet by hand. It is not ground truth, and a clean run is
not a passed check. Extraction is imperfect: a discipline whose index is a
flattened/rotated civil cover sheet, an inline `T100 Site Plan` index, or a
sub-project bound into one PDF can yield zero parsed rows, which turns every
sheet in that volume into false UNLISTED noise — and can equally *suppress* a
real finding the comparison never got to make (e.g. a CNL discipline listed but
never present, whose prefix the gate drops because no sheet of that prefix
exists anywhere).

So **apply your own judgment and do not trust the tool 100%**:

- When a volume parsed **0 index rows** but clearly has sheets, treat the whole
  volume's reconciliation as unverified and **open the PDF yourself** — find the
  real index page, read it, and reconcile by eye. Do not report the resulting
  UNLISTED flood as findings, and do not assume the absence of a finding means
  the volume is clean.
- The tool **cannot read revision-status tables** (sheets marked "never issued"
  in the master index), **cross-prefix duplicate relationships** (two number
  series that are the same sheets, e.g. KS vs MS), or anything raster. These are
  yours to catch by reading the page.
- Your job is to return a **judged, deduplicated list** — true CNL / UNLISTED /
  duplicates separated from parse-gap noise, each grounded in what you saw on
  the page — not to relay the raw grouped counts. The grouped output and the
  scoreboard are inputs to that judgment, not the deliverable.
- A high finding count almost always means a parse gap, not a bad drawing set.
  Diagnose the gap (per-volume `extraction_signal`, `--show-index`,
  `--show-bookmarks`, `--explain`) before reporting numbers.

## Usage

Always invoke through the plugin venv — never rely on PATH resolution.

**Windows (PowerShell):**
```powershell
& "$env:CLAUDE_PLUGIN_ROOT\.venv\Scripts\qc-index.exe" <project-folder>
& "$env:CLAUDE_PLUGIN_ROOT\.venv\Scripts\drawing-index-qc.exe" <project-folder> --mode=preview
& "$env:CLAUDE_PLUGIN_ROOT\.venv\Scripts\drawing-index-qc.exe" <project-folder> --mode=matrix
& "$env:CLAUDE_PLUGIN_ROOT\.venv\Scripts\drawing-index-qc.exe" <project-folder> --mode=sweep
& "$env:CLAUDE_PLUGIN_ROOT\.venv\Scripts\drawing-index-qc.exe" <project-folder> --apply-judgments decisions.json
& "$env:CLAUDE_PLUGIN_ROOT\.venv\Scripts\drawing-index-qc.exe" <project-folder> --mode=emit --reviewer "Your Name"
& "$env:CLAUDE_PLUGIN_ROOT\.venv\Scripts\drawing-index-qc.exe" <project-folder> --mode=emit --kind sheet_in_index_not_in_set
```

**macOS / Linux:**
```bash
"${CLAUDE_PLUGIN_ROOT}/.venv/bin/qc-index" <project-folder>
"${CLAUDE_PLUGIN_ROOT}/.venv/bin/drawing-index-qc" <project-folder> --mode=preview
"${CLAUDE_PLUGIN_ROOT}/.venv/bin/drawing-index-qc" <project-folder> --mode=matrix
"${CLAUDE_PLUGIN_ROOT}/.venv/bin/drawing-index-qc" <project-folder> --mode=sweep
"${CLAUDE_PLUGIN_ROOT}/.venv/bin/drawing-index-qc" <project-folder> --apply-judgments decisions.json
"${CLAUDE_PLUGIN_ROOT}/.venv/bin/drawing-index-qc" <project-folder> --mode=emit --reviewer "Your Name"
"${CLAUDE_PLUGIN_ROOT}/.venv/bin/drawing-index-qc" <project-folder> --mode=emit --kind sheet_in_index_not_in_set
```

Reviewer resolution: `--reviewer` > `qc.config.toml [reviewer] name` > built-in
default `REDICHECK-TKN`. `--kind` (repeatable) restricts emit to the given
finding kind(s); omit it to emit every markup-eligible kind.

Default `--mode=preview`. The flip to `emit` is deferred — see [precision-thresholds.md](../../docs/precision-thresholds.md) (Default-flip status, drawing-index-qc) for the 2026-05-21 baseline and the conditions for revisit.

## Behavior

- Auto-runs `qc-index` when `qc.sqlite` is missing or stale (spec or drawing PDFs).
- **preview**: prints the per-prefix scoreboard (index/bookmark/reconciled/disputed/anomaly counts, with `!` flag on zero-reconciled rows) followed by drawing findings grouped by `kind` from `qc.sqlite`. Shows an UNTRUSTED SCOPE banner when invariants are tripped or Evidence is pending.
- **matrix**: prints the judgment-node worklist as JSON — tripped invariants, findings at `status=evidence`, disputed reconciliation-matrix rows, and the scoreboard (ADR-0026).
- **sweep**: completeness sweep worklist — scoreboard for all prefixes + full raw side-by-side dumps (index rows raw→key vs bookmark rows raw→key, page-ordered) for suspicious prefixes only (any parse anomalies, disputed rows, zero-reconciled, or index_count != bookmark_count). Clean prefixes print as one scoreboard line. Supports `--json`. This is the mandatory judgment node before emit (ADR-0027).
- **emit**: writes one red Revu-style FreeText callout per finding via PyMuPDF (ADR-0012) — the same markup style as spec-check (`qc_core.markup`). Reviewer falls back to `qc.config.toml [reviewer] name`, else the built-in default `REDICHECK-TKN`. Default output is `<name>.marked.pdf`; pass `--in-place` to overwrite sources. **Exits 2 without writing** when any invariant is tripped or any Evidence is unjudged — you cannot sign off on a list with known completeness gaps (ADR-0026 §6a).

## Harness loop (ADR-0026)

This skill is the deterministic harness; you (Claude) fill the judgment nodes. The loop shape is fixed — do not free-drive it:

1. Run `drawing-index-qc` via the plugin venv (see Usage above) with `<project> --mode=matrix`.
2. If `invariants` has tripped rows or `pending_evidence` is non-empty, **judge each disputed item**. For every tripped invariant, open the source PDF page(s) in the `detail` (e.g. via `qc_core` helpers or `PyMuPDF`) and determine what actually happened: real omission, parse gap, sub-project set, parse noise. For every `pending_evidence` finding, decide using its matrix row (`disputed_rows`).
3. Write a decisions file and apply it via the plugin venv with `<project> --apply-judgments decisions.json`. Schema:

   ```json
   {
     "decisions": [
       {"evidence_key": "S4.1", "action": "promote|reclassify",
        "kind": "<required for reclassify>",
        "rationale": "one line, grounded in what you read on the page"},
       {"evidence_key": "EX.A", "action": "dismiss",
        "rationale": "confirmed: no EX.A sheet exists — legend-only reference",
        "raw_text": "EX. A - PARKING SHADING DIAGRAM"}
     ],
     "invariants": [
       {"id": 3, "status": "resolved", "rationale": "what the investigation found"}
     ]
   }
   ```

   **Dismissals require `raw_text`** — copy the exact source text of that evidence row (from the `raw →` column in preview or the `notes` field for parse_anomaly rows). The plugin string-matches this against the stored raw value before writing anything; a mismatch or missing field rejects the whole file (ADR-0027 confirm-by-copying). Promote and reclassify decisions do not require `raw_text`.

   `resolved` = you investigated and judged; `overridden` = the Reviewer made the call (ADR-0024 Resolution). Never resolve an invariant without reading the page it points at; never dismiss Evidence without a rationale. If a parse gap is the cause, the dismissal rationale is the labeled example that improves discovery later — be specific.
4. Run `--mode=sweep` and scan the worklist. Suspicious prefixes (any parse anomalies, disputed rows, zero reconciled, or count mismatch between index and bookmarks) print full raw side-by-side dumps; clean prefixes print as one scoreboard line. For each suspicious prefix, scan for suppressed-class issues: duplicate numbers, gaps in a run, prefix series present in one channel only. Resolve the `completeness_sweep` invariant via `--apply-judgments` with a rationale summarizing what was scanned and what (if anything) was found. Example rationale: "Sweep complete: E (suspicious — mismatch) raw dumps reviewed, E.304 duplicate confirmed; A/S/M/P (clean) attested from scoreboard."
5. Re-run `--mode=preview`; when the UNTRUSTED banner is gone, proceed to triage/emit as usual.

## Dismissal discipline (ADR-0027)

A parse defect produces three kinds of bad output: **spurious** (no real issue — dismiss), **corrupted** (real issue wearing a mangled key — dismissing deletes a true finding), and **suppressed** (real issue for which no finding was ever generated, because the broken extraction made the comparison impossible). Treating a defect-affected cluster as uniformly spurious is the known failure mode (Elk Grove Subaru: `EX. A` unlisted-sheet finding bulk-dismissed as truncation noise; duplicate `E. 304` never detected).

- **Dismiss per row, citing the raw source text of that row** (bookmark title / index line), not the defect. A shared rationale across many rows is invalid — it describes the bug, not the finding.
- **Judgments go through `--apply-judgments` only.** Never write `findings.status` with raw SQL — it bypasses the rationale ledger and coverage accounting.
- **A parse-gap dismissal is coverage debt, not resolution.** If a channel is broken (e.g. one discipline's bookmarks), all downstream checks over that scope are void — including findings that were never emitted. Do not emit/sign off over that scope; the recovery path is fix-the-parser-and-re-run (file the issue), or an explicit Reviewer override (ADR-0024). Never inject "corrected keys" into `qc.sqlite` yourself.
- **Completeness sweep before emit:** dump the raw bookmark list and the raw parsed index side by side, per discipline, and scan for discrepancies reconciliation never surfaced (duplicate numbers, gaps in a run, prefix series present in one channel only). Adjudicate on raw text, not normalized keys.

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
- [ADR-0027](../../docs/adr/0027-parse-defects-corrupt-and-suppress-dismissal-discipline.md)

## Issue filing reflex

If this skill exits non-zero, throws, or the Reviewer says a finding is wrong or missing, offer `/report-issue` (see `/help`).

## Legacy reference

Prior workflow: `legacy/skills/drawing-index-qc/`
