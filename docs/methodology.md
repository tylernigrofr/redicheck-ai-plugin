# Methodology: Claude runs the check, the tool accelerates it

The operating model, stated plainly, because it is easy to invert by accident:

**Claude runs the check. The deterministic parser/DB (`qc-index`, `qc.sqlite`,
the Reconciliation Matrix) is an accelerator, not the check itself.** When the
tool under-covers — zero or partial volumes discovered, a parse gap on a
volume that clearly has sheets — Claude does not report the tool's gap as the
result. Claude reconstructs the check by hand for the affected scope and still
delivers an accurate index check. A degraded tool run is not a degraded
deliverable.

This is the same posture `drawing-index-qc`'s "decision support, not the
verdict" section takes for judging individual findings, extended to the case
where extraction itself failed to cover a volume at all.

## Why this exists

Extraction fails silently in specific, recurring ways: a flattened/rotated
civil cover sheet, a sub-project bound into one PDF, a building-prefixed sheet
numbering scheme the discovery heuristic doesn't recognize (Valrico
Apartments, 2026-07-22 — 0 of 16 drawing volumes discovered). None of these
are reasons to tell the Reviewer "the tool found nothing" and stop. The
Reviewer hired a Review, not a tool run.

## Manual-fallback playbook

Use this when `qc-index` discovers 0 or partial volumes, or when
`drawing-index-qc --mode=preview` shows the UNTRUSTED SCOPE banner for a
volume and diagnosis (`extraction_signal`, `--show-index`, `--show-bookmarks`,
`--explain`) confirms the parser genuinely cannot cover it — not merely that
one channel is noisy.

1. **Enumerate the drawing PDFs in the folder.** List every PDF in the project
   folder and compare that list against the volumes the tool discovered. Any
   PDF the tool has no row for is unverified scope, full stop — not "probably
   fine."

2. **For each undiscovered or under-covered volume, open it and locate every
   index layer.** Per `CONTEXT.md`, a volume typically carries a **Master
   Index** (general/cover sheet, e.g. `G001`) and one **Discipline Index** per
   discipline lead sheet (e.g. `x-M000`, `x-E001`). Neither layer is
   authoritative a priori — read both where present. Extract the sheet
   catalog by hand from PDF bookmarks and/or by reading the index pages
   directly, the same way `drawing-index-qc` would if extraction had worked
   (ADR-0014).

3. **Reconcile by eye.** Compare the hand-extracted catalog against the
   volume's actual sheets (bookmarks/title blocks) the way the Reconciliation
   Matrix would (ADR-0026) — same channels, same judgment, just without the
   deterministic pass. Separate **systematic conventions** (a firm-specific
   numbering scheme, a legend-only cross-reference, a revision-status table
   entry) from **real defects** (a sheet indexed but missing, a sheet present
   but unlisted, a duplicate number). Systematic conventions are not findings;
   real defects are.

4. **Deliver a judged findings list, marked as manually produced.** State
   plainly in the deliverable that this volume (or the whole check) was
   reconstructed by hand because the tool under-covered it, and say why (e.g.
   "16 volumes used building-prefixed sheet numbers the discovery heuristic
   doesn't recognize; hand-reconciled from bookmarks"). Do not present a
   manually-produced list as if it came from `qc.sqlite` — the provenance
   matters for the Reviewer's trust in the next run, and for filing the
   underlying parser gap as an issue.

## Relationship to the deterministic harness

This playbook is the degraded-mode twin of the harness loop in
`skills/drawing-index-qc/SKILL.md` (ADR-0026): same judgment obligations
(read the page, judge per-row, cite what you saw), same domain vocabulary
(Master Index, Discipline Index, Reconciliation Matrix), just without
`qc.sqlite` doing the bookkeeping. Once the parser gap is fixed upstream
(file it via `/report-issue`), the volume goes back through the normal
harness on the next run.
