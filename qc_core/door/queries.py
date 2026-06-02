"""Query helpers for door schedule data."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from qc_core.db import init_db
from qc_core.discovery import qc_sqlite_path


def open_project_db(project_folder: str | Path) -> sqlite3.Connection:
    return init_db(qc_sqlite_path(project_folder))


def all_doors(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT door_no, width, height, door_material, frame_material,
               fire_rating, hardware_set, attributes, source_sheet,
               source_page, sub_schedule_name
        FROM doors
        ORDER BY source_sheet, door_no
        """
    ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["attributes"] = json.loads(item["attributes"] or "{}")
        out.append(item)
    return out


def door_findings(conn: sqlite3.Connection) -> list[dict]:
    from qc_core.door.kinds import DOOR_FINDING_KINDS

    placeholders = ",".join("?" * len(DOOR_FINDING_KINDS))
    rows = conn.execute(
        f"""
        SELECT kind, expected_action, severity, sheet_number, title, notes,
               source_page, drawing_volume_id, context
        FROM findings
        WHERE kind IN ({placeholders})
        ORDER BY kind, sheet_number
        """,
        DOOR_FINDING_KINDS,
    ).fetchall()
    return [dict(r) for r in rows]
