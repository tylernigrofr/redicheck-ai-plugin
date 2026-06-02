"""Door-check PDF annotation emit (ADR-0012 PyMuPDF)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SUBJECT_PREFIX = "door-check"
_SUBJECT = f"{SUBJECT_PREFIX}:door-duplicate-number"

DOOR_CHECK_AUTHOR = "RediCheck Assistant"
_BLUE_STROKE = (0.0, 0.498039, 1.0)

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


@dataclass
class EmitResult:
    emitted: int = 0
    unmatched: list[dict] = field(default_factory=list)
    output_path: Path | None = None


def _pdf_date(dt: datetime) -> str:
    return "D:" + dt.strftime("%Y%m%d%H%M%S") + "Z"


def _delete_door_check_annots(doc) -> None:
    import fitz

    for page in doc:
        to_delete: list[object] = []
        for annot in page.annots() or []:
            info = annot.info or {}
            subj = info.get("subject") or ""
            if subj.startswith(f"{SUBJECT_PREFIX}:"):
                to_delete.append(annot)
        for ann in to_delete:
            page.delete_annot(ann)


def emit_to_pdf(
    pdf_path: Path | str,
    manifest: list[dict],
    output_path: Path | str | None = None,
    in_place: bool = False,
) -> EmitResult:
    """Emit cloudy blue rectangles at row bboxes per ADR markup convention."""
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
        _delete_door_check_annots(doc)

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

            rect = fitz.Rect(bbox[0], bbox[1], bbox[2], bbox[3])
            page = doc[pidx]
            annot = page.add_rect_annot(rect)
            annot.set_border(width=1.25, clouds=1)
            annot.set_colors(stroke=_BLUE_STROKE)
            annot.set_opacity(0.45)
            annot.set_info(
                title=DOOR_CHECK_AUTHOR,
                subject=entry["subject"],
                content=entry.get("comment", ""),
                creationDate=now_pdf,
                modDate=now_pdf,
            )
            annot.update()
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
