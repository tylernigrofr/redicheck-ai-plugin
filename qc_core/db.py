"""SQLite connection and plain-SQL migration runner (ADR-0005)."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path
from typing import Iterable

MIGRATIONS_PACKAGE = "qc_core.migrations"
LATEST_MIGRATION = 17


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


_MIGRATION_FILES = {
    1: "0001_initial.sql",
    2: "0002_toc_classes.sql",
    3: "0003_from_label.sql",
    4: "0004_drawing_index.sql",
    5: "0005_sheet_discipline.sql",
    6: "0006_door_schedule.sql",
    7: "0007_duplicate_sections.sql",
    8: "0008_embedded_reports.sql",
    9: "0009_evidence_lifecycle.sql",
    10: "0010_spec_placeholders.sql",
    11: "0011_ref_classification.sql",
    12: "0012_parse_anomalies.sql",
    13: "0013_extraction_signal.sql",
    14: "0014_foodservice_schedules.sql",
    15: "0015_index_duplicates.sql",
    16: "0016_building_prefix.sql",
    17: "0017_index_layers.sql",
}


def _migration_sql(version: int) -> str:
    filename = _MIGRATION_FILES[version]
    return resources.files(MIGRATIONS_PACKAGE).joinpath(filename).read_text(encoding="utf-8")


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    try:
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        return {int(r[0]) for r in rows}
    except sqlite3.OperationalError:
        return set()


def apply_migrations(conn: sqlite3.Connection, target: int = LATEST_MIGRATION) -> None:
    applied = _applied_versions(conn)
    for version in range(1, target + 1):
        if version in applied:
            continue
        sql = _migration_sql(version)
        conn.executescript(sql)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
            (version,),
        )
        conn.commit()


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) qc.sqlite and apply pending migrations."""
    conn = connect(db_path)
    apply_migrations(conn)
    return conn


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def required_spec_tables() -> Iterable[str]:
    return ("spec_volumes", "spec_sections", "spec_related_refs", "findings")


def required_drawing_tables() -> Iterable[str]:
    return ("drawing_volumes", "drawing_index_entries", "drawing_sheets")


def required_door_tables() -> Iterable[str]:
    return ("door_schedule_regions", "door_column_mappings", "doors")
