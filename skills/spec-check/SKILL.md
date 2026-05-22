---
name: spec-check
description: Query spec findings from qc.sqlite and preview or emit Markups. Preview groups by kind/severity; emit writes a marked-up PDF via PyMuPDF (ADR-0012) that Reviewers open in Revu.
---

# /spec-check

Run spec-check against indexed data in `qc.sqlite`.

## Usage

```bash
spec-check <project-folder> --mode=preview
spec-check <project-folder> --mode=emit --reviewer "REDICHECK-TKN"
spec-check <project-folder> --mode=emit                      # uses qc.config.toml
spec-check <project-folder> --mode=emit --in-place
```

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
2. Run `spec-check <project-folder> --mode=emit --reviewer "<You>"`.
3. Open the resulting `Specs.marked.pdf` (or the in-place file) in Revu and triage in the Markups List.
4. **Upload** the reviewed PDF back to Studio as a new revision.

The PyMuPDF emit path is local-only — no MCP round-trips, no active-document
sequencing, no per-finding variant fallback. A full Kadlec run (~59 markups)
finishes in well under 5 seconds.

## Markup types by kind

| Kind | Type | Anchors on |
|---|---|---|
| `broken_related_ref` | Squiggly | Bad reference text |
| `body_not_in_toc` | Squiggly | Alphabetically-adjacent TOC section (ADR-0011) |
| `division_referenced_but_not_included` | Highlight | `TABLE OF CONTENTS` header |
| `title_mismatch_across_volumes` | — | `info_only`; preview only, no markup emitted |

All markups carry `Author = <reviewer>`, `Subject = "spec-check:<kind>"`, and a
populated `Comments` field — the structure Reviewer triage relies on.

## Related ADRs

- ADR-0009 — finding kinds and Markup Subject convention
- ADR-0010 — idempotent index + auto-refresh
- ADR-0011 — Markup primitives and spec-check Author carve-out (MCP-emit reasoning superseded by ADR-0012 for mass-emit)
- ADR-0012 — PyMuPDF direct-annotation emit supersedes MCP for mass markups

## Issue filing reflex

If this skill exits non-zero, throws, or the Reviewer says a finding is wrong or missing, offer `/report-issue` (see `/help`).
