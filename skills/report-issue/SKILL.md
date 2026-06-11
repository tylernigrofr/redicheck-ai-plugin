---
name: report-issue
description: Submit a structured bug report to Tyler via Linear. Use after skill exceptions or when a Reviewer disputes a finding.
---

# /report-issue

File a bug report without leaving Claude. Reports go to Tyler's private **Linear Feedback** team — not GitHub, not a public tracker.

## When to offer (reflex)

See `/help` for canonical rules. Offer this skill when:

1. A redicheck skill exits non-zero or throws.
2. The Reviewer says a finding is wrong or that something obvious was missed.

## Steps

1. **Gather context** (do not redact project names — Tyler needs them to debug, ADR-0019):
   - Project folder name / path
   - Skill name + command run
   - Plugin version (`.claude-plugin/plugin.json`)
   - Error output or disputed finding
   - Expected vs actual (if Reviewer pushback)
   - Repro steps (if known)

2. **Draft inline** — show Reviewer proposed title + body:

   ```
   Title: [redicheck-ai] [skill] short summary

   ENVIRONMENT
   - Plugin version: …
   - Skill: …
   - OS: …
   - Python: …

   PROJECT
   <folder / client project name>

   WHAT HAPPENED
   …

   COMMAND
   …

   EXPECTED / ACTUAL / REPRO STEPS (as applicable)

   FINGERPRINT
   <16-char hash for dedupe>
   ```

   Or build programmatically via `qc_core.feedback_report.build_body(...)`.

3. **Confirm** — Reviewer approves or edits before submit.

4. **Submit** — run CLI through the plugin venv — never bare PATH:

   **Windows (PowerShell):**
   ```powershell
   & "$env:CLAUDE_PLUGIN_ROOT\.venv\Scripts\report-issue.exe" --title "[skill] short summary" --body-file -
   ```

   **macOS / Linux:**
   ```bash
   "${CLAUDE_PLUGIN_ROOT}/.venv/bin/report-issue" --title "[skill] short summary" --body-file -
   ```

   Paste approved body on stdin. On success, output includes Linear issue id + URL.

   Dry-run (no network):

   **Windows (PowerShell):**
   ```powershell
   & "$env:CLAUDE_PLUGIN_ROOT\.venv\Scripts\report-issue.exe" --title "[skill] short summary" --body-file - --dry-run
   ```

   **macOS / Linux:**
   ```bash
   "${CLAUDE_PLUGIN_ROOT}/.venv/bin/report-issue" --title "[skill] short summary" --body-file - --dry-run
   ```

5. **Confirm** — tell Reviewer Tyler triages Linear Feedback on his regular cadence.

## Guardrails

- Truncate very long logs; mention attachments stay local if needed.
- Include fingerprint for dedupe.
- Do not send duplicate reports for the same failure in one session without asking.

## What this does NOT do

- Does not call `gh issue create` or post to GitHub automatically.
- Does not redact client/project names (private Linear team is the privacy boundary).

## Configuration

| Item | Location |
|------|----------|
| Proxy URL | `qc_core/plugin_config.py` → `FEEDBACK_PROXY_URL` |
| Subject prefix | `[redicheck-ai]` |
| Formatter / CLI | `qc_core/feedback_report.py` |
| Vercel proxy (maintainer) | `services/feedback-proxy/` |

If submit fails (network, proxy down), show the dry-run payload so Tyler can be contacted manually.
