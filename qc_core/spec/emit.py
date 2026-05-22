"""Build the emit manifest and write PDF annotations for spec-check.

`build_manifest()` returns a JSON-serializable list of entries (useful for
preview/audit). `emit_to_pdf()` writes those entries as PDF annotations
directly via PyMuPDF (ADR-0012, supersedes the MCP emit path for mass-emit).
"""

from __future__ import annotations

import html
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

SUBJECT_PREFIX = "spec-check"

SECTION_FORMATS = ("XX XX XX", "XX XXXX", "XXXXXX")
_FORMAT_PATTERNS = {
    "XX XX XX": re.compile(r"\b\d{2} \d{2} \d{2}\b"),
    "XX XXXX": re.compile(r"\b\d{2} \d{4}\b"),
    "XXXXXX": re.compile(r"(?<!\d)\d{6}(?!\d)"),
}


def format_section(canonical: str, fmt: str) -> str:
    """Render a canonical `"NN NN NN[ .NN]"` section number in the given on-page style."""
    if not canonical:
        return canonical
    parts = canonical.split()
    if len(parts) < 3:
        return canonical
    head = parts[:3]
    tail = parts[3:]
    if fmt == "XX XXXX":
        base = f"{head[0]} {head[1]}{head[2]}"
    elif fmt == "XXXXXX":
        base = "".join(head)
    else:
        base = " ".join(head)
    if tail:
        return base + "." + ".".join(tail)
    return base


def detect_section_format(pdf_path: Path | str, toc_start: int, toc_end: int) -> str:
    """Pick the dominant section-number style by regex-scanning TOC pages.

    Falls back to canonical "XX XX XX" when no recognised pattern is found.
    """
    import fitz

    doc = fitz.open(pdf_path)
    try:
        text_parts: list[str] = []
        last = min(toc_end, doc.page_count)
        for p in range(max(0, toc_start - 1), last):
            text_parts.append(doc[p].get_text())
    finally:
        doc.close()
    text = "\n".join(text_parts)
    counts = {fmt: len(pat.findall(text)) for fmt, pat in _FORMAT_PATTERNS.items()}
    if all(v == 0 for v in counts.values()):
        return "XX XX XX"
    return max(counts, key=lambda k: counts[k])

_SUBJECT_BY_KIND = {
    "broken_related_ref": f"{SUBJECT_PREFIX}:broken-related-ref",
    "body_not_in_toc": f"{SUBJECT_PREFIX}:body-not-in-toc",
    "division_referenced_but_not_included": f"{SUBJECT_PREFIX}:division-excluded",
}
_DIVISION_MISSING_SUBJECT = f"{SUBJECT_PREFIX}:division-missing-from-toc"


def section_variants(num: str) -> list[str]:
    """On-page string variants for a CSI section number.

    The indexer normalises section numbers to `"NN NN NN"` (or `"NN NN NN.NN"`
    for 4-part), but specs in the wild use compact and no-space forms. We try
    each variant in order of canonicality.
    """
    if not num:
        return []
    s = num.strip()
    out = [s]
    parts = s.split()
    if len(parts) >= 3:
        head = parts[:3]
        tail = parts[3:]
        joined = f"{head[0]} {head[1]}{head[2]}"
        if tail:
            joined = f"{joined}.{'.'.join(tail).lstrip('.')}" if any("." in t for t in tail) else f"{joined} {' '.join(tail)}"
        if joined not in out:
            out.append(joined)
        nospace = "".join(head) + ("".join(tail) if tail else "")
        if nospace not in out:
            out.append(nospace)
    return out


def adjacent_toc_section(missing: str, toc_numbers: list[str]) -> str | None:
    """Pick the alphabetically-adjacent TOC section to anchor a body_not_in_toc.

    Sort all TOC sections + the missing one; return the predecessor (or
    successor if `missing` sorts before everything).
    """
    if not toc_numbers:
        return None
    ordered = sorted(set(toc_numbers))
    pred: str | None = None
    for n in ordered:
        if n < missing:
            pred = n
        else:
            break
    if pred is not None:
        return pred
    return ordered[0]


def _toc_numbers(conn: sqlite3.Connection, volume_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT tcs.number
        FROM toc_class_sections tcs
        JOIN spec_volumes sv ON sv.toc_class_id = tcs.toc_class_id
        WHERE sv.id = ?
        """,
        (volume_id,),
    ).fetchall()
    return [r[0] for r in rows]


def _toc_page_of(conn: sqlite3.Connection, volume_id: int, section: str) -> int | None:
    row = conn.execute(
        """
        SELECT tcs.toc_page
        FROM toc_class_sections tcs
        JOIN spec_volumes sv ON sv.toc_class_id = tcs.toc_class_id
        WHERE sv.id = ? AND tcs.number = ?
        """,
        (volume_id, section),
    ).fetchone()
    return row[0] if row else None


def _toc_start(conn: sqlite3.Connection, volume_id: int) -> int:
    row = conn.execute(
        "SELECT toc_start FROM spec_volumes WHERE id = ?", (volume_id,)
    ).fetchone()
    return int(row[0]) if row else 1


def _toc_range(conn: sqlite3.Connection, volume_id: int) -> tuple[int, int]:
    row = conn.execute(
        "SELECT toc_start, toc_end FROM spec_volumes WHERE id = ?", (volume_id,)
    ).fetchone()
    if not row:
        return (1, 1)
    return (int(row[0]), int(row[1] or row[0]))


def build_manifest(
    conn: sqlite3.Connection,
    volume_id: int,
    section_format: str = "XX XX XX",
) -> list[dict]:
    """Return one manifest entry per emit_markup finding for the given volume.

    `section_format` controls how section numbers appear in comment text. Use
    `detect_section_format()` against the source PDF to match the project's
    on-page style. Search terms still cover all variants for matching robustness.
    """
    fmt = section_format
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT * FROM findings
        WHERE volume_id = ? AND expected_action = 'emit_markup'
        ORDER BY kind, section, from_section, to_section, source_page
        """,
        (volume_id,),
    ).fetchall()

    toc_nums = _toc_numbers(conn, volume_id)
    toc_divisions = {n.split()[0] for n in toc_nums if n.split()}
    entries: list[dict] = []

    btnt_by_division: dict[str, list] = {}
    for r in rows:
        if r["kind"] == "body_not_in_toc":
            sec = r["section"] or ""
            parts = sec.split()
            if parts:
                btnt_by_division.setdefault(parts[0], []).append(r)
    rolled_divisions = {
        div for div, rs in btnt_by_division.items() if div not in toc_divisions
    }

    for r in rows:
        kind = r["kind"]
        subject = _SUBJECT_BY_KIND[kind]

        if kind == "broken_related_ref":
            terms = section_variants(r["to_section"])
            comment = f"CNL section {format_section(r['to_section'], fmt)}"
            entries.append({
                "kind": kind,
                "subject": subject,
                "comment": comment,
                "page": r["source_page"],
                "search_terms": terms,
                "idempotency_key": f"{subject}|{r['from_section'] or r['from_label']}->{r['to_section']}|p{r['source_page']}",
            })

        elif kind == "body_not_in_toc":
            missing = r["section"] or ""
            div = missing.split()[0] if missing.split() else ""
            if div in rolled_divisions:
                # handled in the per-division rollup pass below
                continue
            anchor = adjacent_toc_section(missing, toc_nums)
            if anchor is None:
                continue
            anchor_page = _toc_page_of(conn, volume_id, anchor) or _toc_start(conn, volume_id)
            terms = section_variants(anchor)
            comment = f"CNL section {format_section(missing, fmt)} in TOC"
            entries.append({
                "kind": kind,
                "subject": subject,
                "comment": comment,
                "page": anchor_page,
                "search_terms": terms,
                "idempotency_key": f"{subject}|{missing}|anchor:{anchor}",
            })

        elif kind == "division_referenced_but_not_included":
            toc_start, toc_end = _toc_range(conn, volume_id)
            div = r["division"]
            anchor_terms = [f"Division {div}", f"DIVISION {div}"]
            entries.append({
                "kind": kind,
                "subject": subject,
                "comment": r["client_comment"],
                "page": toc_start,
                "pages": list(range(toc_start, toc_end + 1)),
                "search_terms": anchor_terms,
                "idempotency_key": f"{subject}|div{div}",
            })

    for div in sorted(rolled_divisions):
        missing_rows = btnt_by_division[div]
        smallest = min(r["section"] for r in missing_rows if r["section"])
        anchor = adjacent_toc_section(smallest, toc_nums)
        if anchor is None:
            continue
        anchor_page = _toc_page_of(conn, volume_id, anchor) or _toc_start(conn, volume_id)
        n = len(missing_rows)
        comment = (
            f"CNL Division {div} in TOC "
            f"({n} section{'s' if n != 1 else ''} in body)"
        )
        entries.append({
            "kind": "body_division_missing_from_toc",
            "subject": _DIVISION_MISSING_SUBJECT,
            "comment": comment,
            "page": anchor_page,
            "search_terms": section_variants(anchor),
            "idempotency_key": f"{_DIVISION_MISSING_SUBJECT}|div{div}",
        })

    return entries


@dataclass
class EmitResult:
    emitted: int = 0
    skipped_existing: int = 0
    unmatched: list[dict] = field(default_factory=list)
    output_path: Path | None = None


def _delete_spec_check_annots(doc) -> None:
    for page in doc:
        to_delete = []
        for annot in page.annots() or []:
            info = annot.info or {}
            subj = info.get("subject") or ""
            if subj.startswith(f"{SUBJECT_PREFIX}:"):
                to_delete.append(annot)
        for annot in to_delete:
            page.delete_annot(annot)


def _find_rect_on_page(page, terms: Iterable[str]):
    for term in terms:
        if not term:
            continue
        hits = page.search_for(term)
        if hits:
            return hits[0]
    return None


_FONT_SIZE = 14.0
_BOX_W = 280.0
_BOX_H = 22.0
_LINE_HEIGHT = 18.0
_BOX_PAD = 6.0
_STACK_GAP = 2.0
_GAP = 8.0
_RED = (0.85, 0.10, 0.10)
_RED_HEX = "#D91A1A"
_MARGIN = 4.0


def _box_size_for(comment: str) -> tuple[float, float]:
    """Pick box w/h so 14pt Helv `comment` fits without clipping when wrapped."""
    import fitz

    width = _BOX_W
    text = comment or ""
    inner_w = width - 2 * _BOX_PAD
    text_w = fitz.get_text_length(text, fontname="helv", fontsize=_FONT_SIZE)
    lines = max(1, int(-(-text_w // inner_w)))  # ceil division
    height = lines * _LINE_HEIGHT + 2 * _BOX_PAD
    return width, max(_BOX_H, height)


def _place_box(page, anchor, w: float, h: float):
    import fitz

    pw, ph = page.rect.width, page.rect.height
    candidates = [
        fitz.Rect(anchor.x1 + _GAP, anchor.y0 - 2, anchor.x1 + _GAP + w, anchor.y0 - 2 + h),
        fitz.Rect(anchor.x0 - _GAP - w, anchor.y0 - 2, anchor.x0 - _GAP, anchor.y0 - 2 + h),
        fitz.Rect(anchor.x0, anchor.y1 + _GAP, anchor.x0 + w, anchor.y1 + _GAP + h),
    ]
    for box in candidates:
        if box.x0 >= _MARGIN and box.x1 <= pw - _MARGIN and box.y0 >= _MARGIN and box.y1 <= ph - _MARGIN:
            return box
    box = candidates[0]
    x0 = max(_MARGIN, min(box.x0, pw - w - _MARGIN))
    y0 = max(_MARGIN, min(box.y0, ph - h - _MARGIN))
    return fitz.Rect(x0, y0, x0 + w, y0 + h)


def _stack_clear(box, existing, page_rect):
    """If `box` overlaps any rect in `existing`, shift down until clear or off-page."""
    import fitz

    h = box.y1 - box.y0
    step = h + _STACK_GAP
    max_y = page_rect.y1 - _MARGIN
    while any(box.intersects(b) for b in existing):
        new_y0 = box.y0 + step
        if new_y0 + h > max_y:
            return box
        box = fitz.Rect(box.x0, new_y0, box.x1, new_y0 + h)
    return box


def _pdf_date(dt: datetime) -> str:
    return "D:" + dt.strftime("%Y%m%d%H%M%S") + "Z"


def _rich_text_payload(comment: str, font_size: float, color_hex: str) -> tuple[str, str]:
    """Return (/DS string, /RC XHTML) matching Bluebeam's native FreeText shape.

    Bluebeam regenerates /AP from /DA on edit-mode toggle when /RC is absent,
    causing a visible font-metric shift. Writing /RC + /DS gives Bluebeam an
    explicit rich-text source so the appearance stays stable.
    """
    ds = (
        f"font: {font_size:g}pt 'Helvetica',sans-serif; "
        f"text-align:left; color:{color_hex}"
    )
    safe = html.escape(comment or "")
    rc = (
        '<?xml version="1.0"?>'
        '<body xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:xfa="http://www.xfa.org/schema/xfa-data/1.0/" '
        'xfa:APIVersion="Acrobat:11.0.0" xfa:spec="2.0.2">'
        '<p dir="ltr">'
        f'<span style="font-size:{font_size:g}pt;font-family:Helvetica;color:{color_hex}">'
        f'{safe}'
        '</span></p></body>'
    )
    return ds, rc


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{int(round(c * 255)):02X}" for c in rgb)


def emit_to_pdf(
    pdf_path: Path | str,
    manifest: list[dict],
    reviewer: str,
    output_path: Path | str | None = None,
    in_place: bool = False,
) -> EmitResult:
    """Write manifest entries as red FreeText annotations via PyMuPDF (ADR-0012).

    Each entry becomes a borderless red-text FreeText box placed adjacent to
    the first matching search term on the entry's page (falling back through
    `pages` if provided). Existing `spec-check:`-subject annotations are
    deleted first so re-running produces no duplicates.

    Default output is `<source>.marked.pdf`; pass `in_place=True` to overwrite.
    """
    import fitz

    src = Path(pdf_path)
    if not in_place and output_path is None:
        out = src.with_name(f"{src.stem}.marked.pdf")
    elif in_place:
        out = src
    else:
        out = Path(output_path)

    now_pdf = _pdf_date(datetime.now(timezone.utc))
    result = EmitResult(output_path=out)
    placed_by_page: dict[int, list] = {}
    doc = fitz.open(src)
    try:
        _delete_spec_check_annots(doc)

        for entry in manifest:
            candidate_pages = entry.get("pages") or [entry["page"]]
            anchor = None
            page = None
            for pnum in candidate_pages:
                pidx = int(pnum) - 1
                if not 0 <= pidx < doc.page_count:
                    continue
                p = doc[pidx]
                hit = _find_rect_on_page(p, entry.get("search_terms", []))
                if hit is not None:
                    anchor = hit
                    page = p
                    break
            if anchor is None or page is None:
                result.unmatched.append(entry)
                continue

            w, h = _box_size_for(entry.get("comment", ""))
            box = _place_box(page, anchor, w, h)
            existing = placed_by_page.setdefault(page.number, [])
            box = _stack_clear(box, existing, page.rect)
            existing.append(box)

            annot = page.add_freetext_annot(
                box,
                entry.get("comment", ""),
                fontsize=_FONT_SIZE,
                fontname="Helv",
                text_color=_RED,
                align=fitz.TEXT_ALIGN_LEFT,
            )
            annot.set_border(width=0)
            annot.set_info(
                title=reviewer,
                subject=entry["subject"],
                content=entry.get("comment", ""),
                creationDate=now_pdf,
                modDate=now_pdf,
            )
            # Lock contents so Revu doesn't auto-refit text on edit-mode toggle.
            annot.set_flags(annot.flags | fitz.PDF_ANNOT_IS_LOCKED_CONTENTS)
            annot.update()

            # Write /DS + /RC so Bluebeam doesn't regenerate /AP from /DA
            # (which otherwise causes a font-metric shift on first click).
            ds, rc = _rich_text_payload(
                entry.get("comment", ""), _FONT_SIZE, _RED_HEX
            )
            doc.xref_set_key(annot.xref, "DS", f"({ds})")
            doc.xref_set_key(annot.xref, "RC", f"({rc})")

            result.emitted += 1

        if in_place:
            tmp = src.with_suffix(src.suffix + ".tmp")
            doc.save(tmp, deflate=True)
            doc.close()
            tmp.replace(src)
        else:
            doc.save(out, deflate=True)
            doc.close()
    finally:
        if not doc.is_closed:
            doc.close()

    return result
