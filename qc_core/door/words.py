"""Word extraction and table row/column clustering."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from qc_core.door.synonyms import HEADER_HINTS, normalize_label


@dataclass
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float = 0.0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Row:
    y: float
    words: list[Word] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in sorted(self.words, key=lambda w: w.x0))

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        ws = self.words
        return (
            min(w.x0 for w in ws),
            min(w.y0 for w in ws),
            max(w.x1 for w in ws),
            max(w.y1 for w in ws),
        )


@dataclass
class Column:
    label: str
    x0: float
    x1: float


def words_from_page(page) -> list[Word]:
    words: list[Word] = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                x0, y0, x1, y1 = span["bbox"]
                words.append(
                    Word(
                        text=text,
                        x0=x0,
                        y0=y0,
                        x1=x1,
                        y1=y1,
                        size=float(span.get("size", 0.0)),
                    )
                )
    return words


def cluster_rows(words: list[Word], *, y_tol: float = 4.0) -> list[Row]:
    buckets: dict[float, list[Word]] = {}
    for w in words:
        y = round(w.y0 / y_tol) * y_tol
        buckets.setdefault(y, []).append(w)
    return [Row(y=y, words=sorted(ws, key=lambda w: w.x0)) for y, ws in sorted(buckets.items())]


def row_header_score(row: Row) -> int:
    score = 0
    for w in row.words:
        token = normalize_label(w.text)
        if token in HEADER_HINTS:
            score += 1
        elif any(token.startswith(h) for h in HEADER_HINTS):
            score += 1
    joined = normalize_label(row.text)
    if re.search(r"\b(MARK|DOOR\s*#|DOOR\s+NO|OPENING)\b", joined):
        score += 2
    if re.search(r"\b(NUMBER|SIZE\s+DOOR|DOOR\s+SIZE)\b", joined):
        score += 2
    if re.search(r"\b(WIDTH|HEIGHT|RATING|HARDWARE|HDW|MAT)\b", joined):
        score += 1
    return score


def merge_header_rows(rows: list[Row], start: int, end: int) -> list[Column]:
    """Build columns from one or two nested header rows."""
    points: list[tuple[float, str]] = []
    for idx in range(start, end + 1):
        if idx > start:
            parent_words = rows[idx - 1].words
            for w in rows[idx].words:
                group = ""
                for pw in parent_words:
                    if abs(pw.cx - w.cx) < 40:
                        group = pw.text
                        break
                label = f"{group} {w.text}".strip() if group else w.text
                points.append((w.x0, label))
        else:
            for w in rows[idx].words:
                points.append((w.x0, w.text))
    points.sort(key=lambda p: p[0])
    cols: list[Column] = []
    for x0, label in points:
        if cols and x0 - cols[-1].x0 < 10:
            cols[-1].label = f"{cols[-1].label} {label}".strip()
            cols[-1].x1 = max(cols[-1].x1, x0 + 12)
        else:
            cols.append(Column(label=label, x0=x0, x1=x0 + 24))
    if cols:
        for i, col in enumerate(cols):
            if i + 1 < len(cols):
                col.x1 = (col.x1 + cols[i + 1].x0) / 2
            else:
                col.x1 = col.x0 + 80
    return cols


def assign_row_to_columns(row: Row, columns: list[Column]) -> dict[str, str]:
    cells: dict[str, list[str]] = {c.label: [] for c in columns}
    for w in row.words:
        col = min(columns, key=lambda c: abs(w.cx - (c.x0 + c.x1) / 2))
        cells[col.label].append(w.text)
    return {label: " ".join(parts).strip() for label, parts in cells.items() if parts}


def split_words_by_x(words: list[Word], gap: float = 120.0) -> list[list[Word]]:
    if not words:
        return []
    ordered = sorted(words, key=lambda w: w.x0)
    groups: list[list[Word]] = [[ordered[0]]]
    for w in ordered[1:]:
        if w.x0 - groups[-1][-1].x1 > gap:
            groups.append([w])
        else:
            groups[-1].append(w)
    return groups
