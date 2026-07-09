"""Locate the two schedules, extract them into qc.sqlite, and cross-check.

Pages are located by scanning page text for the schedule's own title marker
rather than trusting bookmark page numbers (E412's bookmark page is wrong in at
least one real set), then confirmed by the extractor actually finding a header.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path

try:
    import fitz
except ImportError:  # pragma: no cover
    fitz = None  # type: ignore[assignment]

from qc_core.db import init_db
from qc_core.discovery import qc_sqlite_path
from qc_core.foodservice.crosscheck import crosscheck
from qc_core.foodservice.extract import ElecMark, FsItem, extract_elec_marks, extract_fs_items
from qc_core.foodservice.kinds import FS_ELEC_FINDING_KINDS

ELEC_MARKER = "KITCHEN EQUIPMENT SCHEDULE"
FS_MARKER_RE = re.compile(r"(?:Foodservice|Housekeeping)\s+Utility\s+Schedule", re.I)
_SHEET_RE = re.compile(r"\b(QF\d{3}-\d+[A-Z]?|E\d{3})\b")


@dataclass
class FsElecResult:
    fs_items: int
    elec_marks: int
    fs_pages: list[str]
    elec_pages: list[str]
    findings: int


def _relevant_volumes(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT DISTINCT dv.id, dv.pdf_path
        FROM drawing_volumes dv
        JOIN drawing_sheets ds ON ds.volume_id = dv.id
        WHERE ds.title LIKE '%Utility Schedule%'
           OR ds.title LIKE '%ELECTRICAL SCHEDULE%'
        ORDER BY dv.id
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _sheet_for_page(conn: sqlite3.Connection, volume_id: int, page0: int, text: str) -> str:
    row = conn.execute(
        "SELECT sheet_number FROM drawing_sheets WHERE volume_id = ? AND page = ?",
        (volume_id, page0 + 1),
    ).fetchone()
    if row:
        return row["sheet_number"]
    m = _SHEET_RE.search(text)
    return m.group(1) if m else f"p{page0 + 1}"


def _persist(
    conn: sqlite3.Connection,
    fs_items: list[tuple[str, FsItem]],
    elec_marks: list[tuple[str, ElecMark]],
) -> None:
    conn.execute("DELETE FROM fs_equipment_items")
    conn.execute("DELETE FROM elec_kitchen_marks")
    for sheet, it in fs_items:
        x0, y0, x1, y1 = it.bbox
        conn.execute(
            """INSERT INTO fs_equipment_items (
                item_number, qty, description, volts, ph, amps, kw, hz,
                elec_conn_type, elec_rough_in_aff, attributes,
                source_sheet, source_page, source_bbox_x0, source_bbox_y0,
                source_bbox_x1, source_bbox_y1
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (it.item_number, it.qty, it.description, it.volts, it.ph, it.amps,
             it.kw, it.hz, it.elec_conn_type, it.elec_rough_in_aff, "{}",
             sheet, 0, x0, y0, x1, y1),
        )
    for sheet, m in elec_marks:
        x0, y0, x1, y1 = m.bbox
        base = re.sub(r"(?:\.\d{1,2})?[a-z]?$", "", m.mark) or m.mark
        conn.execute(
            """INSERT INTO elec_kitchen_marks (
                mark, base_item, description, volt, phase, watts, amps,
                connection, disconnect, height, attributes,
                source_sheet, source_page, source_bbox_x0, source_bbox_y0,
                source_bbox_x1, source_bbox_y1
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (m.mark, base, m.description, m.volt, m.phase, m.watts, m.amps,
             m.connection, m.disconnect, m.height, "{}",
             sheet, 0, x0, y0, x1, y1),
        )


def _clear_findings(conn: sqlite3.Connection) -> None:
    placeholders = ",".join("?" * len(FS_ELEC_FINDING_KINDS))
    conn.execute(
        f"DELETE FROM findings WHERE kind IN ({placeholders})", FS_ELEC_FINDING_KINDS
    )


def _insert_findings(conn: sqlite3.Connection, findings: list[dict]) -> None:
    severity = {
        "fs_elec_field_mismatch": "high",
        "fs_elec_nominal_voltage_variance": "low",
        "fs_item_missing_in_electrical": "high",
        "elec_mark_missing_in_fs": "medium",
        "fs_item_no_elec_data": "medium",
        "fs_elec_qty_mismatch": "low",
    }
    for f in findings:
        title = f.get("item") or f.get("mark")
        conn.execute(
            """INSERT INTO findings (kind, expected_action, severity, sheet_number,
                                     title, context, notes)
               VALUES (?, 'info_only', ?, ?, ?, ?, ?)""",
            (f["kind"], severity.get(f["kind"], "medium"),
             f.get("source_sheet"), title,
             json.dumps({k: v for k, v in f.items() if k not in ("kind", "note")}),
             f.get("note")),
        )


def index_foodservice_electrical(project_folder: str | Path) -> FsElecResult:
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) is required for the foodservice check")
    from qc_core.drawing.indexer import index_project as index_drawings

    root = Path(project_folder)
    index_drawings(root, force=False)
    conn = init_db(qc_sqlite_path(root))
    try:
        fs_rows: list[tuple[str, FsItem]] = []
        elec_rows: list[tuple[str, ElecMark]] = []
        fs_pages: set[str] = set()
        elec_pages: set[str] = set()

        for vol in _relevant_volumes(conn):
            doc = fitz.open(vol["pdf_path"])
            try:
                for page0 in range(doc.page_count):
                    page = doc.load_page(page0)
                    text = page.get_text("text")
                    if ELEC_MARKER in text.upper():
                        marks = extract_elec_marks(page)
                        if marks:
                            sheet = _sheet_for_page(conn, vol["id"], page0, text)
                            elec_pages.add(sheet)
                            elec_rows.extend((sheet, m) for m in marks)
                    elif FS_MARKER_RE.search(text):
                        items = extract_fs_items(page)
                        if items:
                            sheet = _sheet_for_page(conn, vol["id"], page0, text)
                            fs_pages.add(sheet)
                            fs_rows.extend((sheet, it) for it in items)
            finally:
                doc.close()

        _persist(conn, fs_rows, elec_rows)

        findings = crosscheck([it for _, it in fs_rows], [m for _, m in elec_rows])
        # attach source_sheet to findings keyed by FS item for nicer output
        sheet_by_item = {it.item_number: sheet for sheet, it in fs_rows}
        for f in findings:
            if not f.get("source_sheet") and f.get("item"):
                f["source_sheet"] = sheet_by_item.get(f["item"])

        _clear_findings(conn)
        _insert_findings(conn, findings)
        conn.commit()

        return FsElecResult(
            fs_items=len(fs_rows),
            elec_marks=len(elec_rows),
            fs_pages=sorted(fs_pages),
            elec_pages=sorted(elec_pages),
            findings=len(findings),
        )
    finally:
        conn.close()
