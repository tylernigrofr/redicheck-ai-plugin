"""Build the emit manifest and write PDF annotations for drawing-index QC.

`build_manifest()` returns a JSON-serializable list of entries (preview/audit).
`emit_to_pdf()` writes the same red Revu-style FreeText callout as spec-check
(ADR-0012); styling and placement live in `qc_core.markup`.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Iterable

from qc_core import markup
from qc_core.markup import EmitResult

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


def build_manifest(
    conn: sqlite3.Connection,
    volume_id: int,
    kinds: Iterable[str] | None = None,
) -> list[dict]:
    """Return one manifest entry per emit_markup finding for the given volume.

    `kinds`, when given, restricts the manifest to those finding kinds.
    """
    conn.row_factory = sqlite3.Row
    kind_list = list(kinds) if kinds is not None else None
    query = (
        "SELECT * FROM findings "
        "WHERE drawing_volume_id = ? AND expected_action = 'emit_markup'"
    )
    params: list = [volume_id]
    if kind_list:
        placeholders = ", ".join("?" for _ in kind_list)
        query += f" AND kind IN ({placeholders})"
        params.extend(kind_list)
    query += " ORDER BY kind, sheet_number, source_page"
    rows = conn.execute(query, params).fetchall()

    entries: list[dict] = []
    for r in rows:
        kind = r["kind"]
        subject = _SUBJECT_BY_KIND[kind]
        sheet = r["sheet_number"] or ""
        page = int(r["source_page"] or 1)
        comment = _comment_for(kind, sheet, page)
        entries.append(
            {
                "kind": kind,
                "subject": subject,
                "comment": comment,
                "page": page,
                "search_terms": sheet_variants(sheet),
                "idempotency_key": f"{subject}|{sheet}|p{page}",
            }
        )
    return entries


def emit_to_pdf(
    pdf_path: Path | str,
    manifest: list[dict],
    reviewer: str,
    output_path: Path | str | None = None,
    in_place: bool = False,
) -> EmitResult:
    """Write manifest entries as red Revu-style FreeText callouts (ADR-0012).

    Each entry becomes a borderless red-text FreeText box placed adjacent to the
    first matching sheet-number variant on the entry's page. Existing
    `drawing-index-qc:`-subject annotations are deleted first so re-running
    produces no duplicates. Styling and placement live in `qc_core.markup`.
    """
    import fitz

    src = Path(pdf_path)
    out = markup.resolve_output_path(src, output_path, in_place)
    now_pdf = markup.pdf_date()
    result = EmitResult(output_path=out)
    placed_by_page: dict[int, list] = {}
    doc = fitz.open(src)
    try:
        markup.delete_markups(doc, SUBJECT_PREFIX)

        for entry in manifest:
            page_num = int(entry["page"])
            pidx = page_num - 1
            if not 0 <= pidx < doc.page_count:
                result.unmatched.append(entry)
                continue
            page = doc[pidx]
            anchor = markup.find_rect_on_page(page, entry.get("search_terms", []))
            if anchor is None:
                result.unmatched.append(entry)
                continue

            markup.add_freetext_markup(
                doc,
                page,
                anchor,
                comment=entry.get("comment", ""),
                reviewer=reviewer,
                subject=entry["subject"],
                now_pdf=now_pdf,
                placed_by_page=placed_by_page,
            )
            result.emitted += 1

        markup.save_doc(doc, src, out, in_place)
    finally:
        if not doc.is_closed:
            doc.close()

    return result
