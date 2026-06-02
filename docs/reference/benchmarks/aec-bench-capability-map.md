---
title: AEC-Bench capability map
source: ../papers/aec-bench.md
captured: 2026-05-22
status: actionable
tags: [benchmark, roadmap, aec-bench]
---

# AEC-Bench capability map

Treat AEC-Bench's 9 task families as the **target coverage matrix** for redicheck-ai. Each row below answers: what does this task require, where does redicheck-ai stand, and what's the smallest next step that moves the needle?

See [../papers/aec-bench.md](../papers/aec-bench.md) for the full benchmark description, dataset taxonomy, and published baseline scores.

## Scoring north stars

Published H+ baselines (best across models) from AEC-Bench Table 2 — these are the numbers to beat:

| Task | Best baseline (H+) | Model |
|---|---|---|
| detail-technical-review | 85.7 | GPT-5.2 |
| detail-title-accuracy | 73.3 | Opus 4.6 / Sonnet 4.6 |
| note-callout-accuracy | 35.7 | Opus 4.6 / Sonnet 4.6 |
| cross-reference-resolution | 77.5 | GPT-5.4 |
| sheet-index-consistency | 85.5 | Opus 4.6 |
| cross-reference-tracing | 77.1 | GPT-5.4 |
| spec-drawing-sync | 71.8 | GPT-5.4 |
| drawing-navigation | 100.0 | GPT-5.4 / Opus 4.6 |
| submittal-review | 23.1 | Sonnet 4.6 |

(Nomic Agent figures in Figure 1 of the paper exceed these on aggregate but per-task numbers aren't published in Table 2.)

## Task-by-task coverage

### Intra-Sheet

#### detail-technical-review (14 instances)

Answer localized technical questions about a single detail on a single sheet.

- **What it requires:** Recognize a detail box on a sheet; read its dimensions, materials, notes; answer a targeted Q&A.
- **Current state:** Not covered. No detail-extraction skill yet.
- **Gap:** Sheet → detail bounding-box discovery; text + geometry extraction from a detail region; question answering grounded in that region.
- **Smallest next step:** Detail discovery (find detail boxes on a sheet, extract bounding boxes + titles). Builds on the same PyMuPDF primitives ADR-0012 already uses.

#### detail-title-accuracy (15 instances)

Verify whether a detail's stated title matches the drawn content.

- **What it requires:** Read detail title text + interpret the drawn geometry; flag mismatches.
- **Current state:** Not covered. Pure visual-grounding task.
- **Gap:** Visual reasoning over detail interiors — the paper identifies this as a current foundation-model failure mode.
- **Smallest next step:** Likely deferred until detail discovery exists. Then experiment with VLM-on-cropped-region (rasterize detail bbox at high DPI, ask VLM).

#### note-callout-accuracy (14 instances)

Verify whether callout text correctly describes the element it points to (leader line endpoint).

- **What it requires:** Trace leader lines; align callout text with target geometry.
- **Current state:** Not covered.
- **Gap:** Per the paper, this is the **hardest** task family for current systems (visual-required cases score ~5% across all baselines). Leader-line tracing is geometric, not textual.
- **Smallest next step:** Research only. Watch for new VLM grounding techniques before investing build effort. Could be a future moat if cracked.

### Intra-Drawing

#### cross-reference-resolution (51 instances — largest task)

Identify cross-references on sheets that don't resolve to valid targets (e.g., "See 3/A501" when no detail 3 exists on A501).

- **What it requires:** Extract cross-reference callouts from sheets; build an index of valid targets (sheet + detail number); flag unresolved.
- **Current state:** Partial — drawing index extraction (ADR-0014, recent commits #33) builds the target side. Source-side callout extraction not started.
- **Gap:** Sheet-side callout discovery + matching against drawing index.
- **Smallest next step:** Add callout extraction pass; reuse drawing index as target lookup. **High ROI — largest task family and we're closest to it.**
- **ADR alignment:** ADR-0014 (drawing index), ADR-0015 (master-index reconciliation).

#### cross-reference-tracing (24 instances)

Find ALL source locations referencing a given target detail (reverse direction).

- **What it requires:** Same callout extraction as above, but indexed for reverse lookup.
- **Current state:** Not covered, but falls out cheaply once cross-reference-resolution exists.
- **Gap:** Build the reverse index alongside the forward one.
- **Smallest next step:** Couple with cross-reference-resolution — single extraction pass populates both directions.
- **Paper warning:** Even with parse, baselines drop −0.53% on this task. Exhaustive traversal is the hard part — verify our callout extraction has high recall before claiming coverage.

#### sheet-index-consistency (14 instances)

Compare a drawing set's sheet index against title blocks; flag mismatches.

- **What it requires:** Extract sheet index entries + title-block sheet numbers/titles; cross-check.
- **Current state:** **Closest fit to existing work.** qc-index handles spec indexing; ADR-0014 covers drawing-index extraction via bookmarks + titleblock cross-check; ADR-0015 covers master-index detection and cross-index reconciliation.
- **Gap:** Probably small — likely just need to package outputs in AEC-Bench's JSONL contract.
- **Smallest next step:** Wire the AEC-Bench adapter for this task first. **First benchmark we should be able to score on.**

### Intra-Project

#### drawing-navigation (12 instances)

Locate the correct file, sheet, and detail given a natural-language query.

- **What it requires:** Cross-document retrieval over the project; resolve queries like "show me the door head detail for door 101."
- **Current state:** Partial — drawing index gives us sheet-level retrieval; detail-level retrieval is missing.
- **Gap:** Detail-level addressability (depends on detail discovery from intra-sheet tasks).
- **Smallest next step:** Sheet-level retrieval first (low-hanging — drawing index already supports this). Detail-level once detail discovery lands.
- **Paper note:** Best baseline is **100% (GPT-5.4 H+ and Opus 4.6 H+)** — saturated. We need to match, not beat.

#### spec-drawing-sync (16 instances)

Identify conflicts between specifications and drawings.

- **What it requires:** Spec parsing + drawing parsing + cross-referencing values (materials, sizes, ratings).
- **Current state:** **Partial — door check (ADR-0022) is a vertical slice of this** (door schedule on drawings vs. hardware spec).
- **Gap:** Generalize beyond doors. Spec indexing exists (qc-index, ADR-0010). Need spec value extraction tied to drawing entities.
- **Smallest next step:** After door check ships, identify the next entity type (windows? finishes? structural?) that has a similar schedule+spec pattern. ADR-0022 already frames this as a repeatable pattern.

#### submittal-review (36 instances — 2nd largest)

Evaluate submittals (manufacturer cut sheets, mockups, etc.) for compliance with specs and drawings.

- **What it requires:** Parse submittal PDF (often unstructured manufacturer doc); extract claimed values; compare against spec requirements; apply professional judgment on what counts as compliance.
- **Current state:** Not covered.
- **Gap:** Whole new artifact type. Paper notes baselines max at 23.1 — judgment-heavy + over-generation of findings is a known failure mode.
- **Smallest next step:** Long-term. Could be redicheck-ai's biggest opportunity *because* baselines are so low — but only invest after the easier wins are in.

## Recommended build order

Ranked by expected score gain × proximity to existing work:

1. **sheet-index-consistency** — adapter only; we likely already pass.
2. **cross-reference-resolution** — biggest task family (51 instances); we're halfway there with drawing index.
3. **cross-reference-tracing** — falls out of #2 cheaply.
4. **drawing-navigation** (sheet-level) — drawing index already supports it; saturated baseline so target = match.
5. **spec-drawing-sync** — generalize door check; ADR-0022 frames the pattern.
6. **detail-technical-review** — needs detail-discovery primitive; unlocks #7 and #8.
7. **detail-title-accuracy** — VLM-on-cropped-region, deferred.
8. **submittal-review** — biggest moat opportunity but most expensive; defer.
9. **note-callout-accuracy** — research-only until VLM grounding improves.

## Adapter integration plan

**Verified 2026-05-22:**
- Repo: https://github.com/nomic-ai/aec-bench — public, Apache 2.0, active (last push 2026-05-19).
- Dataset: https://huggingface.co/datasets/nomic-ai/aec-bench — PDFs hosted at `nomic-public-data.com`, fetched per-instance via `environment/manifest.jsonl`.
- Harness: **Harbor** ([harborframework.com](https://harborframework.com/)) — separate framework, runs agents in sandboxed Docker, auto-verifies outputs. CLI: `harbor trials start` (single), `harbor jobs start` (batch). Built-in Claude and Codex agents.
- Task layout: `tasks/<scope>/<type>/<instance>/` with `environment/Dockerfile`, `environment/manifest.jsonl`, and task definition.

Integration steps:

1. Add `benchmarks/aec-bench/` as a git submodule of `nomic-ai/aec-bench`.
2. Install Harbor CLI and verify a baseline `harbor trials start` runs end-to-end with the built-in Claude agent on a single instance (suggest: a `sheet-index-consistency` task — smallest gap to our existing work).
3. Build redicheck-ai as a **Harbor agent** under `redicheck_ai/benchmarks/aec_bench_agent.py` — Harbor's agent interface takes a task environment + instruction, expects structured JSONL findings as output. Route each task type to the matching redicheck-ai skill:
   - `sheet-index-consistency` → qc-index + ADR-0015 reconciliation output
   - `cross-reference-resolution` → drawing-index + callout-extraction
   - (others as we build them)
4. Run task-by-task via Harbor; capture verifier scores into `../runs/YYYY-MM-DD.md`.
5. Track scores over time as a regression suite; gate ADR-driven changes on no-regression.

**Cost / infra notes:**
- Tasks fetch PDFs from `nomic-public-data.com` per instance. Cache locally to avoid re-downloading.
- Harbor runs everything in Docker — our agent needs to be containerizable (plugin venv already is, per ADR-0017).
- Baselines in Table 2 were single-trial — our runs should be too for apples-to-apples.

**Risks:**
- Harbor is new; tooling and docs may be thin. Allow a spike day before committing to the full adapter.
- The benchmark is dated late-2025/early-2026 construction artifacts; our skills are tuned on different projects (e.g., Quarry Oaks per ADR-0006). Expect a calibration gap on the first run.
