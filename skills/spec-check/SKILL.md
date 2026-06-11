---
name: spec-check
description: Query spec findings from qc.sqlite and preview or emit Markups. Preview groups by kind/severity; emit writes a marked-up PDF via PyMuPDF (ADR-0012) that Reviewers open in Revu.
---

# /spec-check

Run spec-check against indexed data in `qc.sqlite`.

## Usage

Always invoke through the plugin venv — never rely on PATH resolution.

**Windows (PowerShell):**
```powershell
& "$env:CLAUDE_PLUGIN_ROOT\.venv\Scripts\spec-check.exe" <project-folder> --mode=preview
& "$env:CLAUDE_PLUGIN_ROOT\.venv\Scripts\spec-check.exe" <project-folder> --mode=emit --reviewer "REDICHECK-TKN"
& "$env:CLAUDE_PLUGIN_ROOT\.venv\Scripts\spec-check.exe" <project-folder> --mode=emit
& "$env:CLAUDE_PLUGIN_ROOT\.venv\Scripts\spec-check.exe" <project-folder> --mode=emit --kind broken_related_ref
& "$env:CLAUDE_PLUGIN_ROOT\.venv\Scripts\spec-check.exe" <project-folder> --mode=emit --kind broken_related_ref --kind toc_not_in_body
& "$env:CLAUDE_PLUGIN_ROOT\.venv\Scripts\spec-check.exe" <project-folder> --mode=emit --in-place
```

**macOS / Linux:**
```bash
"${CLAUDE_PLUGIN_ROOT}/.venv/bin/spec-check" <project-folder> --mode=preview
"${CLAUDE_PLUGIN_ROOT}/.venv/bin/spec-check" <project-folder> --mode=emit --reviewer "REDICHECK-TKN"
"${CLAUDE_PLUGIN_ROOT}/.venv/bin/spec-check" <project-folder> --mode=emit
"${CLAUDE_PLUGIN_ROOT}/.venv/bin/spec-check" <project-folder> --mode=emit --kind broken_related_ref
"${CLAUDE_PLUGIN_ROOT}/.venv/bin/spec-check" <project-folder> --mode=emit --kind broken_related_ref --kind toc_not_in_body
"${CLAUDE_PLUGIN_ROOT}/.venv/bin/spec-check" <project-folder> --mode=emit --in-place
```

Reviewer resolution: `--reviewer` > `qc.config.toml [reviewer] name` >
built-in default `REDICHECK-TKN`. Emit no longer errors when none is set.

`--kind` (repeatable) restricts emit to the given finding kind(s); omit it to
emit every markup-eligible kind. Valid kinds match the preview group headers
(e.g. `broken_related_ref`, `toc_not_in_body`, `duplicate_section_number`).

The legacy `spec-check-mcp` script name remains as a deprecated alias for
backwards compatibility; new callers should use `spec-check`. Despite the
old name, this skill does not use any MCP server — emit is local PyMuPDF
(see ADR-0012).

## Behavior

- Auto-runs indexing when `qc.sqlite` is missing or stale (ADR-0010).
- **preview**: prints findings grouped by `kind` and `expected_action`.
- **emit**: writes annotations directly into the PDF using PyMuPDF
  (ADR-0012). Default output is `<source>.marked.pdf` next to the source;
  `--in-place` overwrites the source. Re-running drops prior `spec-check:`
  annotations and rewrites — no duplication.

## Configuration

Drop a `qc.config.toml` at the project folder root to set a default reviewer:

```toml
[reviewer]
name = "REDICHECK-TKN"
```

`--reviewer` on the CLI overrides the config when both are present.

## Reviewer workflow (Studio-hosted PDF)

1. In Revu, **Download** Specs.pdf from the Studio Project to your project folder.
2. Run `spec-check` via the plugin venv (see Usage above) with `<project-folder> --mode=emit --reviewer "<You>"`.
3. Open the resulting `Specs.marked.pdf` (or the in-place file) in Revu and triage in the Markups List.
4. **Upload** the reviewed PDF back to Studio as a new revision.

The PyMuPDF emit path is local-only — no MCP round-trips, no active-document
sequencing, no per-finding variant fallback. A full Kadlec run (~59 markups)
finishes in well under 5 seconds.

## Markup types by kind

Every emitted markup is a red, bold, Bluebeam-Revu-native FreeText callout
(styling lives in `qc_core.markup`, shared with drawing-index-qc and door-check).
The kind only determines where the callout anchors:

| Kind | Anchors on |
|---|---|
| `broken_related_ref` | Bad reference text |
| `body_not_in_toc` | Alphabetically-adjacent TOC section (ADR-0011) |
| `section_number_mismatch` | Mis-numbered body header (title matches TOC, number differs — #44) |
| `division_referenced_but_not_included` | `TABLE OF CONTENTS` header |
| `title_mismatch_across_volumes` | `info_only`; preview only, no markup emitted |
| `embedded_report_present` | `info_only`; preview only — bound-in non-CSI report (#43), not a defect |

All markups carry `Author = <reviewer>`, `Subject = "spec-check:<kind>"`, and a
populated `Comments` field — the structure Reviewer triage relies on.

## Related ADRs

- ADR-0009 — finding kinds and Markup Subject convention
- ADR-0010 — idempotent index + auto-refresh
- ADR-0011 — Markup primitives and spec-check Author carve-out (MCP-emit reasoning superseded by ADR-0012 for mass-emit)
- ADR-0012 — PyMuPDF direct-annotation emit supersedes MCP for mass markups

## Issue filing reflex

If this skill exits non-zero, throws, or the Reviewer says a finding is wrong or missing, offer `/report-issue` (see `/help`).
