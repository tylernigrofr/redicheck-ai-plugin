"""Per-project drawing-index configuration (ADR-0014, ADR-0005)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TitleBlockRect:
    """Fractions of page width/height for title-block text extraction."""

    x0: float = 0.80
    y0: float = 0.70
    x1: float = 1.0
    y1: float = 1.0
    bottom_strip_y0: float = 0.88


@dataclass(frozen=True)
class DrawingIndexConfig:
    title_block: TitleBlockRect = TitleBlockRect()
    title_block_calibrated: bool = False


DEFAULT_DRAWING_CONFIG = DrawingIndexConfig()


def load_drawing_config(project_folder: str | Path) -> DrawingIndexConfig:
    cfg_path = Path(project_folder) / "qc.config.toml"
    if not cfg_path.is_file():
        return DEFAULT_DRAWING_CONFIG
    try:
        data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return DEFAULT_DRAWING_CONFIG

    block = data.get("drawing", {}).get("title_block", {})
    if not isinstance(block, dict):
        return DEFAULT_DRAWING_CONFIG

    rect = TitleBlockRect(
        x0=float(block.get("x0", 0.80)),
        y0=float(block.get("y0", 0.70)),
        x1=float(block.get("x1", 1.0)),
        y1=float(block.get("y1", 1.0)),
        bottom_strip_y0=float(block.get("bottom_strip_y0", 0.88)),
    )
    calibrated = bool(block.get("calibrated", False))
    return DrawingIndexConfig(title_block=rect, title_block_calibrated=calibrated)
