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

### Wrong-surface detection

If the shell is Linux **and** `${CLAUDE_PLUGIN_ROOT}` is a Windows path, the Reviewer is in Cowork instead of the Claude Code tab. The plugin does not work in Cowork (ADR-0020). Redirect them:

> redicheck-ai needs the **Claude Code** tab in Claude Desktop, not **Cowork**. Switch tabs (left sidebar) and try again.

Do not paste Windows commands for them to run manually.

### Report-issue offers

Offer `/report-issue` when:

1. **Skill exception** — any redicheck skill exits non-zero, throws, or produces an import/command-not-found error.
2. **Reviewer pushback on findings** — the Reviewer says a finding is wrong, or that the tool missed something they expected.

Do **not** offer report-issue for routine "zero findings" unless the Reviewer explicitly expected some.

### Drawing-index manual fallback

`/drawing-index-qc` self-checks coverage (volumes discovered vs. drawing PDFs
present) and checks for per-Discipline embedded indexes before concluding. On
a mismatch, 0 discovered volumes, or a whole Discipline showing UNLISTED, it
drops to manual mode and reads pages by hand rather than trusting an empty or
clean preview. See the skill's own reflexes and
[docs/methodology.md](../../docs/methodology.md).

## Environment

- Venv: `${CLAUDE_PLUGIN_ROOT}/.venv` (managed by SessionStart hook, ADR-0017).
- Config: optional `qc.config.toml` at project root for default reviewer name.
- Updates: public plugin at `tylernigrofr/redicheck-ai-plugin` auto-updates on new releases.

## Docs

- Reviewer onboarding: `docs/onboarding.md`
- Release / support: `docs/release-process.md`
- Operating model (Claude runs the check; tool is an accelerator; manual-fallback playbook when the tool under-covers): `docs/methodology.md`
