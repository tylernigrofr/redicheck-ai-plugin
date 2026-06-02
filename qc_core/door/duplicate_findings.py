"""Detect duplicate door numbers within the same door schedule region (sheet + sub-schedule).

SQL self-join on (source_sheet, sub_schedule_name, door_no); persisted as `door_duplicate_number`.
"""

from __future__ import annotations

import json
import sqlite3

from qc_core.drawing.parse import normalize_sheet_number

DUPLICATE_ROWS_SQL = """
SELECT d.*
FROM doors d
WHERE EXISTS (
  SELECT 1 FROM doors d2
  WHERE d2.id != d.id
    AND d2.door_no = d.door_no
    AND d2.source_sheet = d.source_sheet
    AND COALESCE(d2.sub_schedule_name, '') = COALESCE(d.sub_schedule_name, '')
)
ORDER BY d.source_sheet, COALESCE(d.sub_schedule_name, ''), d.door_no, d.id
"""


def _volume_id_lookup(conn: sqlite3.Connection) -> dict[str, int]:
    lookup: dict[str, int] = {}
    conn.row_factory = sqlite3.Row
    for row in conn.execute(
        """
        SELECT dv.id AS volume_id, ds.sheet_number
        FROM drawing_sheets ds
        JOIN drawing_volumes dv ON dv.id = ds.volume_id
        """
    ):
        lookup[normalize_sheet_number(row["sheet_number"])] = int(row["volume_id"])
    return lookup


def refresh_door_duplicate_number_findings(conn: sqlite3.Connection) -> int:
    """DELETE+reinsert findings for duplicate door marks; returns inserted count."""
    conn.row_factory = sqlite3.Row
    conn.execute("DELETE FROM findings WHERE kind = ?", ("door_duplicate_number",))

    duplicates = conn.execute(DUPLICATE_ROWS_SQL).fetchall()
    vol_by_sheet = _volume_id_lookup(conn)
    inserted = 0

    for r in duplicates:
        bx0, by0, bx1, by1 = r["source_bbox_x0"], r["source_bbox_y0"], r["source_bbox_x1"], r["source_bbox_y1"]
        bbox_ok = all(v is not None for v in (bx0, by0, bx1, by1))

        vid = vol_by_sheet.get(normalize_sheet_number(r["source_sheet"]))
        ss = r["sub_schedule_name"] or ""
        suffix = f" ({ss})" if ss else ""

        duplicate_count = conn.execute(
            """
            SELECT COUNT(*) AS c FROM doors d2
            WHERE d2.door_no = ? AND d2.source_sheet = ?
              AND COALESCE(d2.sub_schedule_name, '') = COALESCE(?, '')
            """,
            (r["door_no"], r["source_sheet"], r["sub_schedule_name"]),
        ).fetchone()["c"]

        notes = (
            f"Door {r['door_no']} appears {duplicate_count}x on sheet "
            f"{r['source_sheet']}{suffix} (within the same schedule table)"
        )
        markup_ctx = {}
        if bbox_ok:
            markup_ctx["markup_bbox"] = [float(bx0), float(by0), float(bx1), float(by1)]

        expected_action = "emit_markup" if bbox_ok and vid is not None else "info_only"

        conn.execute(
            """
            INSERT INTO findings (
                kind,
                expected_action,
                severity,
                drawing_volume_id,
                sheet_number,
                source_page,
                title,
                notes,
                context
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "door_duplicate_number",
                expected_action,
                "medium",
                vid,
                r["source_sheet"],
                int(r["source_page"]),
                r["door_no"],
                notes,
                json.dumps(markup_ctx) if markup_ctx else None,
            ),
        )
        inserted += 1

    return inserted
