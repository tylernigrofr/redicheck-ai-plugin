"""Classify PDFs in a project folder (spec volumes and drawing sets)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PdfClassification = Literal["spec", "drawing_set", "other"]

SPEC_FILENAME_RE = re.compile(
    r"(?:^|[-_\s])(?:specs?|specifications?|project\s+manual)(?:[-_\s]|\.pdf$)|"
    r"specs?\.pdf$|specifications?\.pdf$|project\s+manual\.pdf$",
    re.IGNORECASE,
)

VOLUME_SUFFIX_RE = re.compile(
    r"(?:vol(?:ume)?\s*(\d+)|^(\d+)\s+spec)",
    re.IGNORECASE,
)

# Combined / bundled drawing set (e.g. Kadlec Drawings.pdf).
BUNDLED_DRAWING_RE = re.compile(
    r"(?:^|[-_\s])(?:drawings?|drawing\s+set)(?:[-_\s]|\.pdf$)|"
    r"drawings?\.pdf$|drawing\s+set\.pdf$",
    re.IGNORECASE,
)

_DISCIPLINE = (
    r"civil|structural|architectural|mechanical|plumbing|electrical|"
    r"food\s*service|foodservice|landscape|interior|technology|telecom|"
    r"fire\s*protection|security|mep|gpc"
)

# Per-discipline PDFs and combined-discipline bundles (firm-conventions.md).
DISCIPLINE_DRAWING_RE = re.compile(
    rf"^(?:{_DISCIPLINE})(?:\s+and\s+(?:{_DISCIPLINE}|\w+))?"
    rf"(?:\s+-\s+[^/\\]+)?\.pdf$",
    re.IGNORECASE,
)

# Numbered drawing volumes (e.g. "01 Civil.pdf" or "00-General.pdf") — exclude spec-style names.
NUMBERED_DRAWING_RE = re.compile(
    r"^\d{2}[-\s]+(?!specs?\b|specifications?\b|project\s+manual\b).+\.pdf$",
    re.IGNORECASE,
)

REPORT_SUFFIX_RE = re.compile(
    r"(?:qc\s+report|spec\s+check|drawing\s+index\s+qc)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SpecVolumeDiscovery:
    path: Path
    sort_key: tuple


@dataclass(frozen=True)
class DrawingSetDiscovery:
    path: Path
    sort_key: tuple
    set_pattern: Literal["single_discipline", "bundled_set"]


def _spec_sort_key(path: Path) -> tuple:
    name = path.stem
    m = VOLUME_SUFFIX_RE.search(name)
    if m:
        num = m.group(1) or m.group(2)
        return (0, int(num), name.lower())
    return (1, 0, name.lower())


def _drawing_sort_key(path: Path) -> tuple:
    name = path.stem
    m = re.match(r"^(\d{2})[-\s]+", name)
    if m:
        return (0, int(m.group(1)), name.lower())
    return (1, 0, name.lower())


def is_spec_pdf(path: Path) -> bool:
    if path.suffix.lower() != ".pdf":
        return False
    return bool(SPEC_FILENAME_RE.search(path.name))


def is_drawing_pdf(path: Path) -> bool:
    if path.suffix.lower() != ".pdf":
        return False
    if is_spec_pdf(path):
        return False
    if REPORT_SUFFIX_RE.search(path.stem):
        return False
    if BUNDLED_DRAWING_RE.search(path.name):
        return True
    if DISCIPLINE_DRAWING_RE.match(path.name):
        return True
    if NUMBERED_DRAWING_RE.match(path.name):
        return True
    return False


def drawing_set_pattern(path: Path) -> Literal["single_discipline", "bundled_set"]:
    if BUNDLED_DRAWING_RE.search(path.name):
        return "bundled_set"
    return "single_discipline"


def classify_pdf(path: Path) -> PdfClassification:
    if path.suffix.lower() != ".pdf":
        return "other"
    if is_spec_pdf(path):
        return "spec"
    if is_drawing_pdf(path):
        return "drawing_set"
    return "other"


def discover_spec_pdfs(project_folder: str | Path) -> list[SpecVolumeDiscovery]:
    root = Path(project_folder)
    if not root.is_dir():
        raise FileNotFoundError(f"Project folder not found: {root}")
    pdfs = sorted(
        (p for p in root.iterdir() if p.is_file() and is_spec_pdf(p)),
        key=lambda p: _spec_sort_key(p),
    )
    return [SpecVolumeDiscovery(path=p, sort_key=_spec_sort_key(p)) for p in pdfs]


def discover_drawing_pdfs(project_folder: str | Path) -> list[DrawingSetDiscovery]:
    root = Path(project_folder)
    if not root.is_dir():
        raise FileNotFoundError(f"Project folder not found: {root}")
    pdfs = sorted(
        (p for p in root.iterdir() if p.is_file() and is_drawing_pdf(p)),
        key=lambda p: _drawing_sort_key(p),
    )
    return [
        DrawingSetDiscovery(
            path=p,
            sort_key=_drawing_sort_key(p),
            set_pattern=drawing_set_pattern(p),
        )
        for p in pdfs
    ]


def qc_sqlite_path(project_folder: str | Path) -> Path:
    return Path(project_folder) / "qc.sqlite"
