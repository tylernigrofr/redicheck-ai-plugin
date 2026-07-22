# Dev-mode invocation

When working **inside the redicheck-ai repo** (writing code, running tests, iterating on qc_core), invoke the CLI directly via the repo's own Python environment rather than the plugin venv:

```bash
python -m qc_core qc-index <project-folder>
python -m qc_core spec-check <project-folder> --mode=preview
python -m qc_core drawing-index-qc <project-folder> --mode=preview
python -m qc_core door-check <project-folder> --mode=preview
```

Invoke `python -m qc_core` (the package), not `python -m qc_core.cli`. The
`cli` module is a library of `*_main` entry points with no `__main__` guard, so
running it as a module imports and exits silently (0, no output). The
`qc_core/__main__.py` dispatcher maps the subcommand names above to those entry
points, matching the console scripts in `pyproject.toml`.

`<project-folder>` is always an absolute path to an external project directory containing the target PDFs — not the repo itself.

## What the skill does and does not do

The redicheck skills (`/spec-check`, `/drawing-index-qc`, etc.) **always** invoke the plugin venv at `${CLAUDE_PLUGIN_ROOT}/.venv/…`. They never inspect the shell environment to decide which Python to use, and they never prefer repo code over the installed plugin. If you want to run a dev build, use the `python -m qc_core.cli …` form above in your own shell.

This is intentional: a Reviewer running the plugin gets a known, fingerprint-controlled environment (ADR-0017); a developer running in-repo gets the live source. There is no context-sniffing that switches between the two automatically.

## Cached plugin code

The plugin venv is rebuilt only when `pyproject.toml` or the Python version changes (ADR-0017). If you bump qc_core code without bumping the version, the installed plugin copy is stale until the next version bump triggers a rebuild. Run `python "${CLAUDE_PLUGIN_ROOT}/hooks/ensure_venv.py"` manually (or bump the version) to force a refresh.

## Why a global editable install must not exist

A `pip install -e .` from the system Python places `qc-index`, `spec-check`, etc. on the global PATH. This causes two failure modes:

1. **PATH shadowing**: any bare `qc-index …` in a script or terminal resolves to the global editable, bypassing the plugin venv entirely. The Reviewer gets different (possibly broken) code from what the skill intended to run.
2. **Stale on version bumps**: the editable install reflects the working tree at import time. After a release and venv rebuild, the global script still imports the old repo code — or fails with `ModuleNotFoundError` if the repo has been moved or the package metadata has changed.

The Elk Grove `ModuleNotFoundError` was caused exactly by this: a stale global editable shadowed the plugin venv's `drawing-index-qc`, and when the working tree diverged from the installed metadata Python could no longer import `qc_core`.

**Do not uninstall** a global editable that is being used deliberately in a dev session. But be aware of the risk: as soon as you push a version bump and the plugin venv rebuilds, the global editable becomes a latent trap for bare-PATH invocations.
