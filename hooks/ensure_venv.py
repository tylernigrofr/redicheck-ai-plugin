"""Ensure plugin-local venv matches pyproject.toml + Python version (ADR-0017)."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(
    os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent)
)
VENV_DIR = PLUGIN_ROOT / ".venv"
FINGERPRINT_FILE = VENV_DIR / ".fingerprint"
PYPROJECT = PLUGIN_ROOT / "pyproject.toml"


def compute_fingerprint() -> str:
    pyproject_hash = hashlib.sha256(PYPROJECT.read_bytes()).hexdigest()
    version = subprocess.check_output(
        [sys.executable, "--version"], text=True
    ).strip()
    return f"{pyproject_hash}\n{version}\n"


def read_stored_fingerprint() -> str | None:
    if FINGERPRINT_FILE.is_file():
        return FINGERPRINT_FILE.read_text()
    return None


def pip_path() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "pip.exe"
    return VENV_DIR / "bin" / "pip"


def rebuild() -> None:
    print("redicheck-ai: updating environment…", flush=True)
    if VENV_DIR.exists():
        shutil.rmtree(VENV_DIR)
    subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
    subprocess.check_call([str(pip_path()), "install", "-e", str(PLUGIN_ROOT)])
    FINGERPRINT_FILE.write_text(compute_fingerprint())


def ensure_venv() -> None:
    if not PYPROJECT.is_file():
        sys.exit(f"redicheck-ai: missing {PYPROJECT}")
    target = compute_fingerprint()
    if read_stored_fingerprint() == target and pip_path().is_file():
        return
    rebuild()


if __name__ == "__main__":
    ensure_venv()
