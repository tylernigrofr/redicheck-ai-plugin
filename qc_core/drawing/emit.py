"""Build the emit manifest and write PDF annotations for drawing-index QC.

`build_manifest()` returns a JSON-serializable list of entries (preview/audit).
`emit_to_pdf()` writes Squiggly (and optional Stamp) annotations via PyMuPDF
(ADR-0012).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

SUBJECT_PREFIX = "drawing-index-qc"

_SUBJECT_BY_KIND = {
    "sheet_in_index_not_in_set": f"{SUBJECT_PREFIX}:sheet-in-index-not-in-set",
    "sheet_in_set_not_in_index": f"{SUBJECT_PREFIX}:sheet-in-set-not-in-index",
    "sheet_number_mismatch": f"{SUBJECT_PREFIX}:sheet-number-mismatch",
    "duplicate_sheet_number": f"{SUBJECT_PREFIX}:duplicate-sheet-number",
}

_COMMENT_BY_KIND = {
    "sheet_in_index_not_in_set": "CNL: listed in index but not in drawing set",
    "sheet_in_set_not_in_index": "UNLISTED: in drawing set but not in index",
    "sheet_number_mismatch": "AVW: index vs title block mismatch",
    "duplicate_sheet_number": "IR: duplicate index entry",
}


def sheet_variants(num: str) -> list[str]:
    """On-page string variants for a sheet number (hyphen/space forms)."""
    if not num:
        return []
    s = num.strip().upper()
    out = [s]
    no_hyphen = s.replace("-", "").replace(" ", "")
    if no_hyphen not in out:
        out.append(no_hyphen)
    compact = re.sub(r"[\s\-]+", "", s)
    if compact not in out:
        out.append(compact)
    m = re.match(r"^([A-Z]{1,4})([\d\.]+[A-Z]?)$", compact)
    if m and "-" not in s:
        with_hyphen = f"{m.group(1)}-{m.group(2)}"
        if with_hyphen not in out:
            out.append(with_hyphen)
    return out


def _comment_for(kind: str, sheet_number: str, source_page: int) -> str:
    base = _COMMENT_BY_KIND[kind]
    return f"{base}; sheet {sheet_number}; p. {source_page}"


def build_manifest(conn: sqlite3.Connection, volume_id: int) -> list[dict]:
    """Return one manifest entry per emit_markup finding for the given volume."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT * FROM findings
        WHERE drawing_volume_id = ? AND expected_action = 'emit_markup'
        ORDER BY kind, sheet_number, source_page
        """,
        (volume_id,),
    ).fetchall()

    entries: list[dict] = []
    for r in rows:
        kind = r["kind"]
        subject = _SUBJECT_BY_KIND[kind]
        sheet = r["sheet_number"] or ""
        page = int(r["source_page"] or 1)
        comment = _comment_for(kind, sheet, page)
        stamp = kind == "sheet_in_set_not_in_index"
        entries.append(
            {
                "kind": kind,
                "subject": subject,
                "comment": comment,
                "page": page,
                "search_terms": sheet_variants(sheet),
                "stamp": stamp,
                "idempotency_key": f"{subject}|{sheet}|p{page}",
            }
        )
    return entries


@dataclass
class EmitResult:
    emitted: int = 0
    skipped_existing: int = 0
    unmatched: list[dict] = field(default_factory=list)
    output_path: Path | None = None


def _pdf_date(dt: datetime) -> str:
    return "D:" + dt.strftime("%Y%m%d%H%M%S") + "Z"


def _find_rect_on_page(page, terms: Iterable[str]):
    for term in terms:
        if not term:
            continue
        hits = page.search_for(term)
        if hits:
            return hits[0]
    return None


def _existing_keys(doc) -> set[tuple[str, str, int]]:
    """Subject + Comments + page for existing drawing-index-qc annotations."""
    keys: set[tuple[str, str, int]] = set()
    for page in doc:
        for annot in page.annots() or []:
            info = annot.info or {}
            subj = info.get("subject") or ""
            if subj.startswith(f"{SUBJECT_PREFIX}:"):
                keys.add((subj, info.get("content") or "", page.number + 1))
    return keys


def _stamp_rect(anchor, page_rect):
    import fitz

    w, h = 72.0, 36.0
    gap = 6.0
    x0 = min(anchor.x1 + gap, page_rect.width - w - 4)
    y0 = max(4.0, anchor.y0 - h / 2)
    return fitz.Rect(x0, y0, x0 + w, y0 + h)


def emit_to_pdf(
    pdf_path: Path | str,
    manifest: list[dict],
    reviewer: str,
    output_path: Path | str | None = None,
    in_place: bool = False,
) -> EmitResult:
    """Write manifest entries as Squiggly (+ Stamp when flagged) via PyMuPDF."""
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
    doc = fitz.open(src)
    try:
        existing = _existing_keys(doc)

        for entry in manifest:
            subject = entry["subject"]
            comment = entry.get("comment", "")
            page_num = int(entry["page"])
            key = (subject, comment, page_num)
            if key in existing:
                result.skipped_existing += 1
                continue

            pidx = page_num - 1
            if not 0 <= pidx < doc.page_count:
                result.unmatched.append(entry)
                continue
            page = doc[pidx]
            anchor = _find_rect_on_page(page, entry.get("search_terms", []))
            if anchor is None:
                result.unmatched.append(entry)
                continue

            squiggly = page.add_squiggly_annot(anchor)
            squiggly.set_info(
                title=reviewer,
                subject=subject,
                content=comment,
                creationDate=now_pdf,
                modDate=now_pdf,
            )
            squiggly.update()
            result.emitted += 1
            existing.add(key)

            if entry.get("stamp"):
                stamp_box = _stamp_rect(anchor, page.rect)
                stamp = page.add_stamp_annot(stamp_box, stamp=fitz.STAMP_ForComment)
                stamp.set_info(
                    title=reviewer,
                    subject=subject,
                    content=comment,
                    creationDate=now_pdf,
                    modDate=now_pdf,
                )
                stamp.update()
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
