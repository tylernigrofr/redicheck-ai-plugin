#!/usr/bin/env bash
# SessionStart hook (macOS/Linux) — delegates to shared venv logic (ADR-0017).
set -euo pipefail
python "${CLAUDE_PLUGIN_ROOT}/hooks/ensure_venv.py"
