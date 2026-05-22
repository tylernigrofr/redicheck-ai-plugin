"""Query drawing-index findings from qc.sqlite by kind."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from qc_core.db import init_db
from qc_core.discovery import qc_sqlite_path
from qc_core.drawing.kinds import DRAWING_FINDING_KINDS


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


def findings_by_kind(conn: sqlite3.Connection, kind: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM findings
        WHERE kind = ?
        ORDER BY kind, sheet_number, drawing_volume_id, source_page
        """,
        (kind,),
    ).fetchall()
    return _rows_to_dicts(rows)


def all_findings(conn: sqlite3.Connection) -> list[dict]:
    placeholders = ",".join("?" * len(DRAWING_FINDING_KINDS))
    rows = conn.execute(
        f"""
        SELECT * FROM findings
        WHERE kind IN ({placeholders})
        ORDER BY kind, expected_action, sheet_number, drawing_volume_id
        """,
        DRAWING_FINDING_KINDS,
    ).fetchall()
    return _rows_to_dicts(rows)


def open_project_db(project_folder: str | Path) -> sqlite3.Connection:
    path = qc_sqlite_path(project_folder)
    if not path.is_file():
        raise FileNotFoundError(
            f"No qc.sqlite at {path}. Run qc-index on the project folder first."
        )
    return init_db(path)


def query_sheet_in_index_not_in_set(project_folder: str | Path) -> list[dict]:
    conn = open_project_db(project_folder)
    try:
        return findings_by_kind(conn, "sheet_in_index_not_in_set")
    finally:
        conn.close()


def query_sheet_in_set_not_in_index(project_folder: str | Path) -> list[dict]:
    conn = open_project_db(project_folder)
    try:
        return findings_by_kind(conn, "sheet_in_set_not_in_index")
    finally:
        conn.close()


def query_sheet_number_mismatch(project_folder: str | Path) -> list[dict]:
    conn = open_project_db(project_folder)
    try:
        return findings_by_kind(conn, "sheet_number_mismatch")
    finally:
        conn.close()


def query_duplicate_sheet_number(project_folder: str | Path) -> list[dict]:
    conn = open_project_db(project_folder)
    try:
        return findings_by_kind(conn, "duplicate_sheet_number")
    finally:
        conn.close()
