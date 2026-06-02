---
name: door-check
description: Door schedule duplicate detection and optional PyMuPDF markup emit. Preview surfaces kind-scoped counts; emit draws red Revu-style FreeText callouts at schedule row bboxes for duplicate door numbers within the same schedule table.
---

# /door-check

Run door indexing and duplicate detection against `qc.sqlite` (issue #34).

## Usage

```bash
door-check <project-folder> --mode=preview
door-check <project-folder> --mode=emit --reviewer "REDICHECK-TKN"
door-check <project-folder> --mode=emit --in-place
```

## Behavior

- Auto-runs drawing index + door extraction (issue #33 pipeline) when needed.
- **`door_duplicate_number`** — same `door_no` appearing more than once within one
  source schedule (same sheet + `sub_schedule_name` / bundled table). Persisted in
  `findings` after each door index run.
- **preview** (`--mode=preview`, default): prints findings grouped by `kind`, with
  `emit_markup` counts per section (mirrors `/spec-check`).
- **emit** (`--mode=emit`): writes one red Revu-style FreeText callout per duplicate,
  placed next to the row bbox via PyMuPDF — the same markup style as spec-check
  (`qc_core.markup`). Re-running deletes prior `door-check:` annotations first — no
  duplication. Default output is `<source>.marked.pdf` next to the drawing PDF.
- **Author**: configured Reviewer (`--reviewer` flag, `qc.config.toml [reviewer] name`,
  else default `REDICHECK-TKN`). Subject `door-check:door-duplicate-number`; Comments
  carry the AVW explanation.

## Related

- ADR-0009 — Author / Subject / preview vs emit
- ADR-0012 — PyMuPDF emit
- ADR-0022 — bundled schedule tags (sub-schedule grouping for duplicate scope)

## Issue filing reflex

If emit fails, markups land off-page, or a duplicate looks wrong, offer `/report-issue` (see `/help`).
