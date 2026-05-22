---
name: help
description: Orient on the redicheck-ai plugin and its behavioral reflexes. Use at start of any redicheck-ai work or after a skill exception.
---

# /help

RediCheck AI plugin — local-first QC for construction documents.

## Skills

| Skill | Purpose |
|-------|---------|
| `/setup` | First-run: verify Python, create venv |
| `/qc-index` | Index spec + drawing PDFs → `qc.sqlite` |
| `/spec-check` | Spec findings preview / PyMuPDF emit for Revu |
| `/drawing-index-qc` | Drawing index vs set cross-check (preview / emit) |
| `/report-issue` | Submit a bug report to Tyler (Linear) |

## Typical workflow

1. Download project PDFs to a local folder (from Bluebeam Studio).
2. `/qc-index <project-folder>` — build substrate.
3. `/spec-check <project-folder> --mode=preview` — triage spec findings.
4. `/drawing-index-qc <project-folder> --mode=preview` — triage drawing findings.
5. Emit markups when ready (`--mode=emit --reviewer "Your Name"`).

## Reflex rules (canonical)

Offer `/report-issue` when:

1. **Skill exception** — any redicheck skill exits non-zero, throws, or produces an import/command-not-found error.
2. **Reviewer pushback on findings** — the Reviewer says a finding is wrong, or that the tool missed something they expected.

Do **not** offer report-issue for routine "zero findings" unless the Reviewer explicitly expected some.

## Environment

- Venv: `${CLAUDE_PLUGIN_ROOT}/.venv` (managed by SessionStart hook, ADR-0017).
- Config: optional `qc.config.toml` at project root for default reviewer name.
- Updates: public plugin at `tylernigrofr/redicheck-ai-plugin` auto-updates on new releases.

## Docs

- Reviewer onboarding: `docs/onboarding.md`
- Release / support: `docs/release-process.md`
