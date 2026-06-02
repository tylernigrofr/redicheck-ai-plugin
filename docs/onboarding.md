# Reviewer onboarding

Install redicheck-ai in Claude Desktop and run your first spec-check.

## Before Claude — install these two things

| Prerequisite | Install |
|--------------|---------|
| **Python 3.11+** | [python.org/downloads](https://www.python.org/downloads/) — check "Add Python to PATH" on Windows |
| **Git** | `winget install Git.Git` (Windows) — needed by the plugin marketplace to fetch the plugin |
| **Claude Desktop** | [claude.ai/download](https://claude.ai/download) — sign in |

`gh` is optional for v0.1.0 — the plugin marketplace is public.

Tyler may need to screenshare the Python install once. Everything after is Claude-driven.

## Pick the right tab

Claude Desktop has two tabs in the left sidebar: **Cowork** and **Claude Code**. **Use Claude Code.** Cowork runs in the cloud and cannot reach your local PDFs or Bluebeam Revu, so redicheck-ai will not work there (ADR-0020). If a skill ever tells you to "switch to the Code tab," that's why.

## Paste this into Claude

After prerequisites are installed, open a **new Claude Code conversation** (not Cowork) and paste:

```text
I just installed the redicheck-ai plugin prerequisites (Python 3.11+, Claude Desktop).

Please:
1. Run /plugin marketplace add tylernigrofr/redicheck-ai-plugin
2. Install the redicheck-ai plugin from that marketplace
3. Run /setup to verify my environment
4. Run /help so I know what skills are available

Stop after /help and wait for my project folder path.
```

## After setup

Typical flow on a project folder with downloaded PDFs:

1. `/qc-index <project-folder>`
2. `/spec-check <project-folder> --mode=preview`
3. `/drawing-index-qc <project-folder> --mode=preview`

Use `/report-issue` if something breaks or a finding looks wrong — it submits a structured bug report to Tyler's Linear Feedback inbox (one click from Claude).
