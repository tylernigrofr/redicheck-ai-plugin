"""Door schedule indexing: discovery, resolution, extraction (issue #33)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

try:
    import fitz
except ImportError:  # pragma: no cover
    fitz = None  # type: ignore[assignment]

from qc_core.db import init_db
from qc_core.door.column_mapper import apply_canonical_row, resolve_column_map
from qc_core.door.discover import ScheduleRegion, discover_regions_on_page, extract_rows_from_region
from qc_core.door.duplicate_findings import refresh_door_duplicate_number_findings
from qc_core.door.kinds import DOOR_FINDING_KINDS
from qc_core.door.resolution import (
    ResolutionDiff,
    diff_regions,
    load_stored_regions,
    persist_regions,
    regions_for_extraction,
)
from qc_core.drawing.parse import normalize_sheet_number


@dataclass
class DoorIndexResult:
    discovered_regions: int
    resolved_regions: int
    doors_extracted: int
    non_door_excluded: int
    resolution_diff: ResolutionDiff | None
    needs_resolution: bool


def _clear_door_findings(conn: sqlite3.Connection) -> None:
    placeholders = ",".join("?" * len(DOOR_FINDING_KINDS))
    conn.execute(f"DELETE FROM findings WHERE kind IN ({placeholders})", DOOR_FINDING_KINDS)


def _insert_finding(
    conn: sqlite3.Connection,
    *,
    kind: str,
    sheet_number: str,
    notes: str | None = None,
    title: str | None = None,
    expected_action: str = "info_only",
) -> None:
    conn.execute(
        """
        INSERT INTO findings (
            kind, expected_action, severity, sheet_number, title, notes
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (kind, expected_action, "low", sheet_number, title, notes),
    )


def _architectural_sheets(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            """
            SELECT ds.sheet_number, ds.page, dv.pdf_path
            FROM drawing_sheets ds
            JOIN drawing_volumes dv ON dv.id = ds.volume_id
            WHERE ds.discipline = 'Architectural'
            ORDER BY ds.sheet_number
            """
        ).fetchall()
    ]


def _page_for_sheet(conn: sqlite3.Connection, sheet_number: str) -> tuple[str, int] | None:
    key = normalize_sheet_number(sheet_number)
    for row in _architectural_sheets(conn):
        if normalize_sheet_number(row["sheet_number"]) == key:
            return row["pdf_path"], int(row["page"]) - 1
    return None


def discover_project_regions(conn: sqlite3.Connection) -> list[ScheduleRegion]:
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) is required for door schedule discovery")
    regions: list[ScheduleRegion] = []
    for row in _architectural_sheets(conn):
        pdf_path = row["pdf_path"]
        page_idx = int(row["page"]) - 1
        doc = fitz.open(pdf_path)
        try:
            regions.extend(
                discover_regions_on_page(row["sheet_number"], page_idx, doc.load_page(page_idx))
            )
        finally:
            doc.close()
    return regions


def _region_id(conn: sqlite3.Connection, region: ScheduleRegion) -> int | None:
    x0, y0, x1, y1 = region.bbox
    row = conn.execute(
        """
        SELECT id FROM door_schedule_regions
        WHERE sheet_number = ? AND page = ?
          AND abs(bbox_x0 - ?) < 1 AND abs(bbox_y0 - ?) < 1
          AND abs(bbox_x1 - ?) < 1 AND abs(bbox_y1 - ?) < 1
          AND coalesce(sub_schedule_name, '') = coalesce(?, '')
        """,
        (region.sheet_number, region.page, x0, y0, x1, y1, region.sub_schedule_name),
    ).fetchone()
    return int(row["id"]) if row else None


def extract_project_doors(
    conn: sqlite3.Connection,
    *,
    regions: list[ScheduleRegion] | None = None,
) -> tuple[int, int, list[str]]:
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) is required for door schedule extraction")
    if regions is None:
        regions = regions_for_extraction(conn)
    conn.execute("DELETE FROM doors")
    extracted = 0
    excluded = 0
    unfamiliar: set[str] = set()

    page_cache: dict[tuple[str, int], object] = {}
    pdf_docs: dict[str, object] = {}

    try:
        for region in regions:
            loc = _page_for_sheet(conn, region.sheet_number)
            if not loc:
                continue
            pdf_path, page_idx = loc
            if pdf_path not in pdf_docs:
                pdf_docs[pdf_path] = fitz.open(pdf_path)
            doc = pdf_docs[pdf_path]
            cache_key = (pdf_path, page_idx)
            if cache_key not in page_cache:
                page_cache[cache_key] = doc.load_page(page_idx)
            page = page_cache[cache_key]

            rows = extract_rows_from_region(page, region)
            if not rows:
                continue

            raw_labels = list({k for row in rows for k in row.raw.keys()})
            column_map, unknown = resolve_column_map(conn, raw_labels)
            unfamiliar.update(unknown)
            region_id = _region_id(conn, region)

            seen_keys: set[tuple[str, str, str]] = set()
            for row in rows:
                if not row.is_door:
                    excluded += 1
                    continue
                canonical, attributes = apply_canonical_row(row.raw, column_map)
                door_no = canonical.get("door_no") or row.door_no
                dedupe_key = (region.sheet_number, region.sub_schedule_name, door_no)
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                x0, y0, x1, y1 = row.bbox
                conn.execute(
                    """
                    INSERT INTO doors (
                        door_no, width, height, door_material, frame_material,
                        fire_rating, hardware_set, attributes, source_sheet,
                        source_page, source_bbox_x0, source_bbox_y0,
                        source_bbox_x1, source_bbox_y1, sub_schedule_name, region_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        door_no,
                        canonical.get("width"),
                        canonical.get("height"),
                        canonical.get("door_material"),
                        canonical.get("frame_material"),
                        canonical.get("fire_rating"),
                        canonical.get("hardware_set"),
                        json.dumps(attributes),
                        region.sheet_number,
                        region.page + 1,
                        x0,
                        y0,
                        x1,
                        y1,
                        region.sub_schedule_name,
                        region_id,
                    ),
                )
                extracted += 1
    finally:
        for doc in pdf_docs.values():
            doc.close()

    return extracted, excluded, sorted(unfamiliar)


def index_project_doors(
    project_folder: str | Path,
    *,
    auto_accept_resolution: bool = False,
) -> DoorIndexResult:
    from qc_core.discovery import qc_sqlite_path
    from qc_core.drawing.indexer import index_project as index_drawings

    root = Path(project_folder)
    index_drawings(root, force=False)
    conn = init_db(qc_sqlite_path(root))
    try:
        discovered = discover_project_regions(conn)
        stored = load_stored_regions(conn)
        resolution_diff = diff_regions(discovered, stored) if stored else None
        needs_resolution = bool(
            stored
            and resolution_diff
            and (resolution_diff.added or resolution_diff.removed)
        )

        if not stored:
            persist_regions(conn, discovered, source="auto")
        elif auto_accept_resolution:
            persist_regions(conn, discovered, source="auto", replace=True)

        _clear_door_findings(conn)
        if needs_resolution and not auto_accept_resolution:
            for added in resolution_diff.added if resolution_diff else []:
                _insert_finding(
                    conn,
                    kind="door_schedule_region_reviewer_resolution",
                    sheet_number=added.sheet_number,
                    title=added.sub_schedule_name,
                    notes=f"discovered new region bbox={added.bbox}",
                )
            for removed in resolution_diff.removed if resolution_diff else []:
                _insert_finding(
                    conn,
                    kind="door_schedule_region_reviewer_resolution",
                    sheet_number=removed.sheet_number,
                    title=removed.sub_schedule_name,
                    notes=f"stored region no longer discovered id={removed.id}",
                )

        extracted, excluded, unfamiliar = extract_project_doors(conn)
        if excluded:
            _insert_finding(
                conn,
                kind="door_schedule_non_door_rows_excluded",
                sheet_number="*",
                notes=f"schedule contains non-door rows: {excluded} rows excluded",
            )
        if unfamiliar:
            _insert_finding(
                conn,
                kind="door_schedule_unmapped_columns",
                sheet_number="*",
                notes="unmapped columns: " + ", ".join(unfamiliar[:20]),
            )

        refresh_door_duplicate_number_findings(conn)

        conn.commit()
        resolved = load_stored_regions(conn)
        return DoorIndexResult(
            discovered_regions=len(discovered),
            resolved_regions=len(resolved),
            doors_extracted=extracted,
            non_door_excluded=excluded,
            resolution_diff=resolution_diff,
            needs_resolution=needs_resolution and not auto_accept_resolution,
        )
    finally:
        conn.close()
