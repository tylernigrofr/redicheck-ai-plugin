"""Query findings from qc.sqlite by kind."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from qc_core.db import init_db
from qc_core.discovery import qc_sqlite_path
from qc_core.spec.kinds import SPEC_FINDING_KINDS


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


def findings_by_kind(conn: sqlite3.Connection, kind: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM findings
        WHERE kind = ?
        ORDER BY kind, section, from_section, to_section, source_page
        """,
        (kind,),
    ).fetchall()
    return _rows_to_dicts(rows)


def all_findings(conn: sqlite3.Connection) -> list[dict]:
    placeholders = ",".join("?" * len(SPEC_FINDING_KINDS))
    rows = conn.execute(
        f"""
        SELECT * FROM findings
        WHERE kind IN ({placeholders})
        ORDER BY kind, expected_action, section, from_section, to_section
        """,
        SPEC_FINDING_KINDS,
    ).fetchall()
    return _rows_to_dicts(rows)


def emit_markup_findings(conn: sqlite3.Connection) -> list[dict]:
    placeholders = ",".join("?" * len(SPEC_FINDING_KINDS))
    rows = conn.execute(
        f"""
        SELECT * FROM findings
        WHERE kind IN ({placeholders}) AND expected_action = 'emit_markup'
        ORDER BY kind, section, from_section, to_section
        """,
        SPEC_FINDING_KINDS,
    ).fetchall()
    return _rows_to_dicts(rows)


def open_project_db(project_folder: str | Path) -> sqlite3.Connection:
    path = qc_sqlite_path(project_folder)
    if not path.is_file():
        raise FileNotFoundError(
            f"No qc.sqlite at {path}. Run qc-index on the project folder first."
        )
    return init_db(path)


def query_body_not_in_toc(project_folder: str | Path) -> list[dict]:
    conn = open_project_db(project_folder)
    try:
        return findings_by_kind(conn, "body_not_in_toc")
    finally:
        conn.close()


def query_toc_not_in_body(project_folder: str | Path) -> list[dict]:
    conn = open_project_db(project_folder)
    try:
        return findings_by_kind(conn, "toc_not_in_body")
    finally:
        conn.close()


def query_broken_related_refs(project_folder: str | Path) -> list[dict]:
    conn = open_project_db(project_folder)
    try:
        return findings_by_kind(conn, "broken_related_ref")
    finally:
        conn.close()


def query_division_excluded(project_folder: str | Path) -> list[dict]:
    conn = open_project_db(project_folder)
    try:
        return findings_by_kind(conn, "division_referenced_but_not_included")
    finally:
        conn.close()
