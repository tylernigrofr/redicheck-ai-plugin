---
name: setup
description: First-run setup for redicheck-ai — verify Python 3.11+, create the plugin venv. Use when a Reviewer first installs the plugin or after a failed environment check.
---

# /setup

Bootstrap the redicheck-ai plugin environment. Run once after install, or when a skill fails with a missing command / import error.

## Prerequisites (host machine)

See `docs/onboarding.md`:

1. **Python 3.11+** on PATH
2. **Claude Desktop** signed in

## Steps

1. **Verify Python 3.11+**

   ```bash
   python --version
   ```

   Require `Python 3.11` or newer. If missing or too old, stop and point the Reviewer to `docs/onboarding.md` prereqs.

2. **Create / refresh plugin venv**

   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/hooks/ensure_venv.py"
   ```

   On rebuild, the script prints `redicheck-ai: updating environment…` once (~30–90s). Steady state is silent.

3. **Smoke test**

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/.venv/Scripts/spec-check" --help
   ```

   On macOS/Linux use `.venv/bin/spec-check`.

4. Confirm the Reviewer can run `/help` and `/spec-check` on a project folder.

5. **Optional:** verify `/report-issue` dry-run:

   ```bash
   report-issue --title "setup smoke test" --body "post-setup check" --dry-run
   ```

   Output should show the proxy URL and JSON payload. Omit `--dry-run` to submit a real Linear issue.

## Notes

- SessionStart hook runs the same `ensure_venv.py` on every session (ADR-0017).
- Plugin marketplace is public — no `gh auth` required for install.
