"""Region discovery and row extraction from door schedules."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from qc_core.door.synonyms import (
    NON_DOOR_SUB_SCHEDULE_RE,
    SCHEDULE_TITLE_RE,
    normalize_label,
)
from qc_core.door.words import (
    Row,
    Word,
    assign_row_to_columns,
    cluster_rows,
    merge_header_rows,
    row_header_score,
    split_words_by_x,
    words_from_page,
)

DOOR_TAG_RE = re.compile(
    r"^(?:\d{2,4}[A-Za-z]?|U\d{1,3}[A-Za-z]?|[A-Z]\d{3,4}[A-Za-z]?)$"
)
ROOM_CODE_RE = re.compile(r"^([A-Z]\d{3,4}[A-Za-z]?)\b")
HARDWARE_CODE_RE = re.compile(r"^(?:F\d+|G\d+|HM\d?|WD\d?|FG\d?|HG\d?|ALUM|SCWD)$", re.I)
DIMENSION_RE = re.compile(r"\d\s*['\u2019-]\s*\d|'\s*-|\d/\d")
STOP_ROW_RE = re.compile(
    r"(?:DOOR SCHEDULE NOTES|SCHEDULE NOTES|^NOTES$|WINDOW SCHEDULE|"
    r"DOOR TYPES|TYPICAL DOOR|REVISIONS$|SEE SHEET)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ScheduleRegion:
    sheet_number: str
    page: int
    bbox: tuple[float, float, float, float]
    sub_schedule_name: str
    header_labels: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class ExtractedDoorRow:
    door_no: str
    raw: dict[str, str]
    bbox: tuple[float, float, float, float]
    is_door: bool = True
    exclude_reason: str | None = None


def _region_key(sheet: str, bbox: tuple[float, float, float, float], name: str) -> tuple:
    return (
        sheet,
        round(bbox[0]),
        round(bbox[1]),
        round(bbox[2]),
        round(bbox[3]),
        normalize_label(name),
    )


def _is_valid_schedule_title(title: str) -> bool:
    t = title.strip()
    if len(t) > 120 or len(t) < 8:
        return False
    upper = t.upper()
    if upper.startswith(("SEE ", "REFERENCE", "FOR DOOR", "REFER TO", "NOTE:")):
        return False
    if "FOR DOOR SCHEDULE" in upper and "FLOOR" not in upper and "OPENING SCHEDULE" not in upper:
        return False
    if "PANEL GLAZING" in upper or "PERIMETER FENCE" in upper or "SM4" in upper:
        return False
    if "SHEET INDEX" in upper or "COVER SHEET" in upper:
        return False
    if re.search(r"OPENING\s+SCHEDULE\s*-\s*(COMMERCIAL|DETENTION)", upper):
        return True
    if SCHEDULE_TITLE_RE.search(t):
        return True
    return False


def _titles_from_row(row: Row) -> list[str]:
    text = row.text.strip()
    matches = list(SCHEDULE_TITLE_RE.finditer(text))
    if not matches:
        return []
    titles: list[str] = []
    for m in matches:
        clause_start = text.rfind(".", 0, m.start())
        chunk = text[(clause_start + 1 if clause_start >= 0 else 0) : m.end()].strip(" .")
        if len(chunk) > 8:
            titles.append(chunk)
        else:
            titles.append(m.group(0).strip())
    return [t for t in titles if _is_valid_schedule_title(t)]


def _title_from_row(row: Row) -> str | None:
    titles = _titles_from_row(row)
    return titles[0] if titles else None


def _find_header_block(rows: list[Row], start: int) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    best_score = 0
    for i in range(start, min(start + 25, len(rows))):
        score = row_header_score(rows[i])
        if score < 2:
            continue
        end = i
        if i + 1 < len(rows) and row_header_score(rows[i + 1]) >= 1:
            end = i + 1
        total = score + (row_header_score(rows[end]) if end > i else 0)
        if total > best_score:
            best_score = total
            best = (i, end)
    return best


def _row_x_band(row: Row, padding: float = 40.0) -> tuple[float, float]:
    x0, _, x1, _ = row.bbox
    return (x0 - padding, x1 + padding)


def _bands_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def _find_header_in_x_band(rows: list[Row], x_band: tuple[float, float]) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    best_score = 0
    for i, row in enumerate(rows):
        if not _bands_overlap(_row_x_band(row), x_band):
            continue
        score = row_header_score(row)
        if score < 2:
            continue
        end = i
        if i + 1 < len(rows) and row_header_score(rows[i + 1]) >= 1:
            if _bands_overlap(_row_x_band(rows[i + 1]), x_band):
                end = i + 1
        total = score + (row_header_score(rows[end]) if end > i else 0)
        if total > best_score:
            best_score = total
            best = (i, end)
    return best


def _discover_title_anchored_regions(
    sheet_number: str,
    page_idx: int,
    page,
    rows: list[Row],
    seen: set[tuple],
) -> list[ScheduleRegion]:
    regions: list[ScheduleRegion] = []
    for i, row in enumerate(rows):
        for title in _titles_from_row(row):
            if NON_DOOR_SUB_SCHEDULE_RE.search(title):
                continue
            x_band = _row_x_band(row, padding=80.0)
            header = _find_header_in_x_band(rows, x_band)
            if not header:
                continue
            h_start, h_end = header
            data_end = len(rows) - 1
            for j in range(max(h_end, i) + 1, len(rows)):
                if not _bands_overlap(_row_x_band(rows[j]), x_band):
                    continue
                if STOP_ROW_RE.search(rows[j].text):
                    data_end = j - 1
                    break
                if _title_from_row(rows[j]) and j > h_end + 3:
                    data_end = j - 1
                    break
            block_rows = [
                r
                for r in rows[h_start : data_end + 1]
                if _bands_overlap(_row_x_band(r), x_band)
            ]
            if len(block_rows) < 4:
                continue
            bbox = (
                min(r.bbox[0] for r in block_rows),
                min(r.bbox[1] for r in block_rows),
                max(r.bbox[2] for r in block_rows),
                max(r.bbox[3] for r in block_rows),
            )
            cols = merge_header_rows(rows, h_start, h_end)
            preview = ScheduleRegion(
                sheet_number=sheet_number,
                page=page_idx,
                bbox=bbox,
                sub_schedule_name=title,
                header_labels=tuple(c.label for c in cols),
            )
            if not _region_passes_quality(page, preview):
                continue
            key = _region_key(sheet_number, bbox, title)
            if key not in seen:
                seen.add(key)
                regions.append(preview)
    return regions


def _words_in_bbox(words: list[Word], bbox: tuple[float, float, float, float]) -> list[Word]:
    x0, y0, x1, y1 = bbox
    return [w for w in words if w.x0 >= x0 - 2 and w.x1 <= x1 + 2 and w.y0 >= y0 - 2 and w.y1 <= y1 + 2]


def discover_regions_on_page(
    sheet_number: str, page_idx: int, page
) -> list[ScheduleRegion]:
    words = words_from_page(page)
    if not words:
        return []

    all_rows = cluster_rows(words)
    seen: set[tuple] = set()
    return _discover_title_anchored_regions(sheet_number, page_idx, page, all_rows, seen)


def _looks_like_door_tag(token: str) -> bool:
    if not token or HARDWARE_CODE_RE.match(token):
        return False
    if re.match(r"^\d{4}$", token) and int(token) > 2020:
        return False
    if DOOR_TAG_RE.match(token):
        return True
    return bool(ROOM_CODE_RE.match(token))


def _row_has_dimensions(raw: dict[str, str]) -> bool:
    joined = " ".join(raw.values())
    return bool(DIMENSION_RE.search(joined))


def _region_passes_quality(page, region: ScheduleRegion) -> bool:
    rows = extract_rows_from_region(page, region)
    door_rows = [r for r in rows if r.is_door and r.door_no]
    if len(door_rows) < 3:
        return False
    with_dims = sum(1 for r in door_rows if _row_has_dimensions(r.raw))
    room_codes = sum(1 for r in door_rows if ROOM_CODE_RE.match(r.door_no))
    if with_dims + room_codes < max(3, int(len(door_rows) * 0.25)):
        return False
    x0, y0, x1, y1 = region.bbox
    if (x1 - x0) < 120 or (y1 - y0) < 40:
        return False
    return True


def _row_has_door_tag(row: Row) -> bool:
    for w in row.words[:6]:
        if _looks_like_door_tag(w.text):
            return True
    for token in row.text.split():
        if _looks_like_door_tag(token):
            return True
    return False


def _normalize_door_no(value: str) -> str | None:
    for token in value.split():
        if _looks_like_door_tag(token):
            return token
    return None


def _extract_door_no(raw: dict[str, str], *, sub_schedule_name: str) -> str | None:
    for key in raw:
        norm = normalize_label(key)
        if any(h in norm for h in ("MARK", "OPENING", "DOOR #", "DOOR NO", "NUMBER")):
            tag = _normalize_door_no(raw[key])
            if tag:
                return tag
    for key, val in raw.items():
        if "TO" in normalize_label(key) and "ROOM" in normalize_label(key):
            m = ROOM_CODE_RE.match(val.strip())
            if m:
                return m.group(1)
            tag = _normalize_door_no(val)
            if tag:
                return tag
    for val in raw.values():
        tag = _normalize_door_no(val)
        if tag:
            return tag
    return None


def _is_non_door_row(door_no: str | None, raw: dict[str, str], sub_schedule_name: str) -> str | None:
    if NON_DOOR_SUB_SCHEDULE_RE.search(sub_schedule_name):
        return "sub_schedule_not_doors"
    joined = " ".join(raw.values()).upper()
    if " GATE" in joined or joined.startswith("GATE"):
        return "site_gate"
    if door_no and re.match(r"^G\d+$", door_no, re.I):
        return "gate_code"
    return None


def extract_rows_from_region(page, region: ScheduleRegion) -> list[ExtractedDoorRow]:
    words = _words_in_bbox(words_from_page(page), region.bbox)
    rows = cluster_rows(words)
    if not rows:
        return []

    header = _find_header_block(rows, 0)
    if not header:
        return []
    h_start, h_end = header
    columns = merge_header_rows(rows, h_start, h_end)

    extracted: list[ExtractedDoorRow] = []
    for row in rows[h_end + 1 :]:
        if STOP_ROW_RE.search(row.text):
            break
        if row_header_score(row) >= 3:
            continue
        raw = assign_row_to_columns(row, columns)
        if not any(raw.values()):
            continue
        door_no = _extract_door_no(raw, sub_schedule_name=region.sub_schedule_name)
        if not door_no:
            continue
        if not _row_has_dimensions(raw) and not ROOM_CODE_RE.match(door_no):
            continue
        exclude = _is_non_door_row(door_no, raw, region.sub_schedule_name)
        extracted.append(
            ExtractedDoorRow(
                door_no=door_no,
                raw=raw,
                bbox=row.bbox,
                is_door=exclude is None,
                exclude_reason=exclude,
            )
        )
    return extracted
