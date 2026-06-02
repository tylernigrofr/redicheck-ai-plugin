# Reference library

External research, competitor analysis, and benchmark tracking that informs redicheck-ai's direction. The goal: stay on the cutting edge of AEC-agent tooling and avoid duplicating work that someone else has already published a better method for.

## Folder layout

| Folder | Contents |
|---|---|
| `papers/` | Academic papers and technical reports relevant to AEC document agents. |
| `competitors/` | Products doing what we're doing (or adjacent). One file per company/tool. |
| `benchmarks/` | Benchmark definitions we're targeting and capability maps. AEC-Bench is the primary measure. |
| `benchmarks/runs/` | Dated score snapshots from running our tool against a benchmark. |
| `applied/` | Short notes when a finding has been converted into an ADR, issue, or design decision. Each note links back to the source. |

## Workflow

1. **Capture** — drop a new file in the right subfolder with the frontmatter below.
2. **Triage** — review weekly. Decide: noise, watch-list, or actionable. Update the entry's `status`.
3. **Apply** — when actionable, open a GitHub issue or write an ADR, then add a stub in `applied/` linking source → outcome.

## Frontmatter template

Every entry (except this README and run snapshots) starts with:

```markdown
---
title: <short title>
source: <url or "private">
captured: YYYY-MM-DD
status: raw | triaged | watch | actionable | applied | superseded
tags: [aec, agent, parsing, ...]
applied_to: [adr-NNNN, issue-NN]   # optional
---
```

`status` meanings:
- **raw** — captured but not read carefully
- **triaged** — read; relevance assessed
- **watch** — keep tracking; not actionable now
- **actionable** — should drive an issue or ADR
- **applied** — converted into project work (see `applied_to`)
- **superseded** — replaced by a newer entry

## Index

### Papers

- [AEC-Bench](papers/aec-bench.md) — Nomic's multimodal benchmark for AEC agents. 9 task families, 196 instances. *Primary external benchmark for redicheck-ai.*

### Competitors

- [AEC QC AI landscape](competitors/aec-qc-ai-analysis.md) — full landscape scan (17 companies) with open-source build stack analysis. Covers Buildcheck, Helonic, Document Crunch, Togal, TwinKnowledge, CivCheck, AutoReview.AI, etc.
- [Structured (getstructured.ai)](competitors/structured.md) — YC-backed, MEP/civil/structural focus, Syska Hennessy as customer. **Closest direct competitor to redicheck-ai's product vision.**

### Benchmarks

- [AEC-Bench capability map](benchmarks/aec-bench-capability-map.md) — maps each AEC-Bench task family to redicheck-ai's current state and what we need to build to score.
- [Run snapshots](benchmarks/runs/) — dated score records.

### Applied

*(empty — populate as research converts into ADRs / issues)*
