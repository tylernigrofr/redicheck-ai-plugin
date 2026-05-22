# SessionStart hook (Windows) — delegates to shared venv logic (ADR-0017).
$ErrorActionPreference = "Stop"
python "$env:CLAUDE_PLUGIN_ROOT/hooks/ensure_venv.py"
