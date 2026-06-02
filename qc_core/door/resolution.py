"""Persistent Reviewer resolution for door schedule regions (ADR-0024)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from qc_core.door.discover import ScheduleRegion


@dataclass(frozen=True)
class StoredRegion:
    id: int
    sheet_number: str
    page: int
    bbox: tuple[float, float, float, float]
    sub_schedule_name: str
    source: str


@dataclass
class ResolutionDiff:
    added: list[ScheduleRegion]
    removed: list[StoredRegion]
    unchanged: list[StoredRegion]


def _row_to_stored(row: sqlite3.Row) -> StoredRegion:
    return StoredRegion(
        id=row["id"],
        sheet_number=row["sheet_number"],
        page=row["page"],
        bbox=(row["bbox_x0"], row["bbox_y0"], row["bbox_x1"], row["bbox_y1"]),
        sub_schedule_name=row["sub_schedule_name"] or "",
        source=row["source"],
    )


def region_identity(
    sheet_number: str,
    bbox: tuple[float, float, float, float],
    sub_schedule_name: str,
) -> tuple:
    return (
        sheet_number,
        round(bbox[0]),
        round(bbox[1]),
        round(bbox[2]),
        round(bbox[3]),
        (sub_schedule_name or "").strip().upper(),
    )


def load_stored_regions(conn: sqlite3.Connection) -> list[StoredRegion]:
    rows = conn.execute(
        """
        SELECT id, sheet_number, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
               sub_schedule_name, source
        FROM door_schedule_regions
        ORDER BY sheet_number, page, bbox_y0
        """
    ).fetchall()
    return [_row_to_stored(r) for r in rows]


def persist_regions(
    conn: sqlite3.Connection,
    regions: list[ScheduleRegion],
    *,
    source: str = "auto",
    replace: bool = False,
) -> None:
    if replace:
        conn.execute("DELETE FROM door_schedule_regions")
    for region in regions:
        x0, y0, x1, y1 = region.bbox
        conn.execute(
            """
            INSERT OR IGNORE INTO door_schedule_regions (
                sheet_number, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                sub_schedule_name, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                region.sheet_number,
                region.page,
                x0,
                y0,
                x1,
                y1,
                region.sub_schedule_name,
                source,
            ),
        )


def diff_regions(
    discovered: list[ScheduleRegion], stored: list[StoredRegion]
) -> ResolutionDiff:
    disc_map = {
        region_identity(r.sheet_number, r.bbox, r.sub_schedule_name): r
        for r in discovered
    }
    store_map = {
        region_identity(s.sheet_number, s.bbox, s.sub_schedule_name): s for s in stored
    }
    added = [disc_map[k] for k in disc_map.keys() - store_map.keys()]
    removed = [store_map[k] for k in store_map.keys() - disc_map.keys()]
    unchanged = [store_map[k] for k in disc_map.keys() & store_map.keys()]
    return ResolutionDiff(added=added, removed=removed, unchanged=unchanged)


def stored_to_schedule(stored: StoredRegion) -> ScheduleRegion:
    return ScheduleRegion(
        sheet_number=stored.sheet_number,
        page=stored.page,
        bbox=stored.bbox,
        sub_schedule_name=stored.sub_schedule_name,
    )


def regions_for_extraction(conn: sqlite3.Connection) -> list[ScheduleRegion]:
    stored = load_stored_regions(conn)
    return [stored_to_schedule(s) for s in stored]
