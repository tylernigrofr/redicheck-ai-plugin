# redicheck-ai

AI-augmented QC review tooling for architectural drawings, built around the RediCheck methodology.

## Agent skills

### Issue tracker

Issues and PRDs live as GitHub issues on `tylernigrofr/redicheck-ai`. Use the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Fixture drift

When a fixture snapshot test fails after a code change, investigate every delta before regenerating. Treating "+1 entry" as routine has repeatedly hidden parser regressions. See `docs/agents/fixture-drift.md`.

### Dev-mode invocation

When iterating on qc_core in-repo, use `python -m qc_core.cli …` directly — skills always use the plugin venv, never repo code. See `docs/agents/dev-mode.md`.
