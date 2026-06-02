# Benchmark runs

Dated score snapshots from running redicheck-ai against a benchmark. One file per run, named `YYYY-MM-DD-<benchmark>.md` (e.g., `2026-06-01-aec-bench.md`).

## Snapshot template

```markdown
---
benchmark: aec-bench
run_date: YYYY-MM-DD
commit: <git sha of redicheck-ai at time of run>
model: <foundation model + harness, e.g., claude-opus-4-7 / Claude Code>
notes: <anything unusual about this run>
---

# AEC-Bench — YYYY-MM-DD

## Scores

| Category | Task | Reward (0-100) | Baseline (best H+) | Delta |
|---|---|---|---|---|
| Intra-Sheet | detail-technical-review | — | 85.7 | — |
| Intra-Sheet | detail-title-accuracy | — | 73.3 | — |
| Intra-Sheet | note-callout-accuracy | — | 35.7 | — |
| Intra-Drawing | cross-reference-resolution | — | 77.5 | — |
| Intra-Drawing | cross-reference-tracing | — | 77.1 | — |
| Intra-Drawing | sheet-index-consistency | — | 85.5 | — |
| Intra-Project | drawing-navigation | — | 100.0 | — |
| Intra-Project | spec-drawing-sync | — | 71.8 | — |
| Intra-Project | submittal-review | — | 23.1 | — |

## Failures of note

- *(list specific instances where we underperformed — root cause, hypothesis)*

## Changes since last run

- *(what landed in redicheck-ai between this run and the prior one)*
```

Don't delete old runs — they're the regression record.
