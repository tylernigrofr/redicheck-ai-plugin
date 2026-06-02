"""Door-check PDF annotation emit (ADR-0012 PyMuPDF).

Emits the same red Revu-style FreeText callout as spec-check, anchored at the
duplicate door-schedule row bbox. Styling and placement live in `qc_core.markup`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from qc_core import markup
from qc_core.markup import EmitResult

SUBJECT_PREFIX = "door-check"
_SUBJECT = f"{SUBJECT_PREFIX}:door-duplicate-number"

_SUBJECT_BY_KIND = {
    "door_duplicate_number": _SUBJECT,
}


def build_manifest(conn: sqlite3.Connection, volume_id: int) -> list[dict]:
    """One manifest row per duplicate-door markup for the drawing volume."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT kind, drawing_volume_id, sheet_number, source_page, title, notes,
               context
        FROM findings
        WHERE kind = ?
          AND drawing_volume_id = ?
          AND expected_action = 'emit_markup'
        ORDER BY sheet_number, source_page, title, id
        """,
        ("door_duplicate_number", volume_id),
    ).fetchall()

    manifest: list[dict] = []
    for i, r in enumerate(rows):
        ctx = {}
        raw = r["context"]
        if raw:
            try:
                ctx = json.loads(raw)
            except json.JSONDecodeError:
                ctx = {}
        bbox_list = ctx.get("markup_bbox")
        if not bbox_list or len(bbox_list) != 4:
            continue

        sheet = r["sheet_number"] or ""
        door_no = r["title"] or ""
        page = int(r["source_page"] or 1)
        comment = (
            "AVW: duplicate door number in schedule; "
            f"door='{door_no}'; sheet {sheet}; "
            + (r["notes"] or "")
        )
        manifest.append(
            {
                "kind": r["kind"],
                "subject": _SUBJECT_BY_KIND[r["kind"]],
                "comment": comment.strip(),
                "page": page,
                "bbox": tuple(float(x) for x in bbox_list),
                "idempotency_key": f"{_SUBJECT}|{sheet}|p{page}|{door_no}|{i}",
            }
        )

    return manifest


def emit_to_pdf(
    pdf_path: Path | str,
    manifest: list[dict],
    reviewer: str,
    output_path: Path | str | None = None,
    in_place: bool = False,
) -> EmitResult:
    """Write manifest entries as red Revu-style FreeText callouts (ADR-0012).

    Each entry becomes a borderless red-text FreeText box placed next to the
    duplicate door row's bbox. Existing `door-check:`-subject annotations are
    deleted first so re-running produces no duplicates. Styling and placement
    live in `qc_core.markup`.
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
            bbox = entry.get("bbox")
            if not bbox or len(bbox) != 4:
                result.unmatched.append(entry)
                continue

            page = doc[pidx]
            anchor = fitz.Rect(bbox[0], bbox[1], bbox[2], bbox[3])
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
