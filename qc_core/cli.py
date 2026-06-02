"""CLI entry points: qc-index, spec-check, and drawing-index-qc (all PyMuPDF emit, ADR-0012)."""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

from qc_core.discovery import qc_sqlite_path
from qc_core.drawing.kinds import DRAWING_FINDING_KINDS
from qc_core.drawing import emit as drawing_emit
from qc_core.drawing import indexer as drawing_indexer
from qc_core.drawing import queries as drawing_queries
from qc_core.door import emit as door_emit_mod
from qc_core.door import indexer as door_indexer
from qc_core.door import queries as door_queries
from qc_core.door.kinds import DOOR_FINDING_KINDS
from qc_core.spec import emit as emit_mod
from qc_core.spec import indexer, queries
from qc_core.spec.kinds import SPEC_FINDING_KINDS


def _load_reviewer_from_config(project_folder: Path) -> str | None:
    cfg = project_folder / "qc.config.toml"
    if not cfg.is_file():
        return None
    try:
        data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    reviewer = data.get("reviewer", {}).get("name")
    return reviewer if isinstance(reviewer, str) and reviewer else None



def _needs_full_index(project_folder: str | Path) -> bool:
    return indexer.needs_reindex(project_folder) or drawing_indexer.needs_reindex(
        project_folder
    )


def _run_qc_index(project_folder: str | Path, *, force: bool = False) -> int:
    db_path = qc_sqlite_path(project_folder)
    print(f"qc.sqlite: {db_path}")

    try:
        spec_summaries = indexer.index_project(project_folder, force=force)
    except FileNotFoundError as exc:
        print(f"spec: {exc}", file=sys.stderr)
        spec_summaries = []

    for s in [x for x in spec_summaries if x.get("indexed")]:
        m = s["meta"]
        print(
            f"  spec indexed volume {s['volume_id']}: "
            f"TOC {m['toc_section_count']} sections, "
            f"body {m['body_section_count']} sections, "
            f"{s.get('related_refs_count', 0)} cross-refs"
        )
    for s in [x for x in spec_summaries if not x.get("indexed")]:
        print(f"  spec skipped volume {s.get('volume_id')}: {s.get('reason')}")

    drawing_summaries = drawing_indexer.index_project(project_folder, force=force)
    for s in [x for x in drawing_summaries if x.get("indexed")]:
        m = s["meta"]
        print(
            f"  drawing indexed volume {s['volume_id']}: "
            f"{s['sheets']} sheets, {s['index_entries']} index rows, "
            f"bookmark parse {m['bookmark_parse_rate']:.0%}"
        )
        if m.get("bookmark_parse_warning"):
            print(
                f"    WARNING: low bookmark parse rate on {Path(s['pdf_path']).name} "
                f"({m['bookmark_parse_rate']:.0%}) — firm convention may differ"
            )
    for s in [x for x in drawing_summaries if not x.get("indexed")]:
        print(f"  drawing skipped volume {s.get('volume_id')}: {s.get('reason')}")

    return 0


def _format_door_finding(row: dict) -> str:
    kind = row["kind"]
    sev = row.get("severity") or "medium"
    sheet = row.get("sheet_number") or ""
    if kind == "door_duplicate_number":
        page = row.get("source_page")
        door = row.get("title") or ""
        suffix = f" p.{page}" if page is not None else ""
        notes = row.get("notes") or ""
        base = f"  [{sev}] {sheet}{suffix} door={door}".rstrip()
        return (f"{base} — {notes}").strip() if notes else base

    notes = row.get("notes") or ""
    subtitle = row.get("title") or ""
    extras = f" ({subtitle})" if subtitle else ""
    return (f"  [{sev}] {sheet}{extras} — {notes}" if notes else f"  [{sev}] {sheet}{extras}").strip()


def _door_check_preview(conn, project_folder: str | Path) -> None:
    findings = door_queries.door_findings(conn)

    by_kind: dict[str, list[dict]] = defaultdict(list)
    for row in findings:
        by_kind[row["kind"]].append(row)

    print(f"=== door-check preview ({Path(project_folder).name}) ===")
    print(f"Total findings: {len(findings)}\n")

    for kind in DOOR_FINDING_KINDS:
        rows = by_kind.get(kind, [])
        if not rows:
            continue
        emit_count = sum(
            1 for r in rows if r.get("expected_action") == "emit_markup"
        )
        print(f"## {kind} ({len(rows)} rows, {emit_count} emit_markup)")
        for row in rows[:50]:
            print(_format_door_finding(row))
        if len(rows) > 50:
            print(f"  ... and {len(rows) - 50} more")
        print()


def _door_emit(conn, args) -> int:
    rows = conn.execute(
        "SELECT id, pdf_path FROM drawing_volumes ORDER BY id"
    ).fetchall()

    total_emitted = 0
    total_unmatched = 0
    for row in rows:
        manifest = door_emit_mod.build_manifest(conn, row["id"])
        if not manifest:
            continue
        pdf_path = Path(row["pdf_path"])
        result = door_emit_mod.emit_to_pdf(
            pdf_path,
            manifest,
            in_place=args.in_place,
        )
        total_emitted += result.emitted
        total_unmatched += len(result.unmatched)
        print(
            f"volume {row['id']}: {result.emitted} emitted, "
            f"{len(result.unmatched)} unmatched -> {result.output_path}"
        )
        for entry in result.unmatched:
            print(f"  unmatched: {entry['subject']} p.{entry['page']} bbox")

    print(f"TOTAL: {total_emitted} emitted, {total_unmatched} unmatched")
    return 0 if total_unmatched == 0 else 1


def door_check_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Door schedule discovery, resolution checkpoint, and extraction."
    )
    parser.add_argument("project_folder", help="Folder containing drawing PDF(s)")
    parser.add_argument(
        "--mode",
        choices=["preview", "emit"],
        default="preview",
        help="preview: grouped door findings; emit: AVW cloudy markups via PyMuPDF (ADR-0012)",
    )
    parser.add_argument(
        "--accept-resolution",
        action="store_true",
        help="Accept auto-discovery diff and update stored regions (ADR-0024)",
    )
    parser.add_argument(
        "--map-column",
        nargs=2,
        metavar=("RAW", "CANONICAL"),
        action="append",
        default=[],
        help="Persist a column mapping (e.g. 'TO: ROOM' door_no)",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the source PDF instead of writing <name>.marked.pdf (emit mode)",
    )
    args = parser.parse_args(argv)

    from qc_core.db import init_db
    from qc_core.discovery import qc_sqlite_path
    from qc_core.door.column_mapper import save_column_mapping

    if _needs_full_index(args.project_folder):
        print("qc.sqlite missing or stale — running qc-index...")
        _run_qc_index(args.project_folder)

    db_path = qc_sqlite_path(args.project_folder)
    if args.map_column:
        conn = init_db(db_path)
        try:
            for raw, canonical in args.map_column:
                save_column_mapping(conn, raw, canonical)
                print(f"  mapped {raw!r} -> {canonical!r}")
            conn.commit()
        finally:
            conn.close()

    result = door_indexer.index_project_doors(
        args.project_folder,
        auto_accept_resolution=args.accept_resolution,
    )
    print(
        f"door-check: discovered {result.discovered_regions} regions, "
        f"resolved {result.resolved_regions}, extracted {result.doors_extracted} doors"
    )
    if result.non_door_excluded:
        print(f"  excluded {result.non_door_excluded} non-door rows")
    if result.needs_resolution:
        diff = result.resolution_diff
        print(
            f"  RESOLUTION CHECKPOINT: +{len(diff.added)} / -{len(diff.removed)} regions "
            f"(re-run with --accept-resolution to persist)"
        )
        return 1

    conn = door_queries.open_project_db(args.project_folder)
    try:
        if args.mode == "emit":
            return _door_emit(conn, args)
        _door_check_preview(conn, args.project_folder)
    finally:
        conn.close()

    return 0


def qc_index_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover spec and drawing PDFs, index into qc.sqlite."
    )
    parser.add_argument("project_folder", help="Folder containing project PDF(s)")
    parser.add_argument("--force", action="store_true", help="Re-index even if mtime unchanged")
    args = parser.parse_args(argv)
    return _run_qc_index(args.project_folder, force=args.force)


def _format_drawing_finding(row: dict) -> str:
    return (
        f"  [{row.get('severity', 'medium')}] {row.get('sheet_number')} "
        f"vol={row.get('drawing_volume_id')} p.{row.get('source_page')} "
        f"{row.get('notes') or ''}"
    ).rstrip()


def _format_finding(row: dict) -> str:
    kind = row["kind"]
    if kind == "body_not_in_toc":
        return f"  [{row.get('severity', 'medium')}] {row['section']} — {row.get('title') or ''} (body p.{row.get('body_page')})"
    if kind == "toc_not_in_body":
        return f"  [{row.get('severity', 'medium')}] {row['section']} — {row.get('title') or ''} (TOC p.{row.get('toc_page')})"
    if kind == "broken_related_ref":
        return (
            f"  [{row.get('severity', 'medium')}] {row.get('from_section')} -> {row.get('to_section')} "
            f"(p.{row.get('source_page')})"
        )
    if kind == "division_referenced_but_not_included":
        return f"  [high] Division {row.get('division')} excluded — {row.get('client_comment')}"
    if kind == "broken_related_ref_div01":
        return (
            f"  [info] {row.get('from_section')} -> {row.get('to_section')} "
            f"(p.{row.get('source_page')}) [aggregated]"
        )
    if kind == "title_mismatch_across_volumes":
        return (
            f"  [{row.get('severity', 'low')}] {row['section']} — "
            f"{row.get('title') or ''} (TOC p.{row.get('toc_page')}) "
            f"{row.get('notes') or ''}"
        ).rstrip()
    return f"  {kind}: {row}"


def _emit(conn, args) -> int:
    reviewer = args.reviewer or _load_reviewer_from_config(Path(args.project_folder))
    if not reviewer:
        print(
            "ERROR: --reviewer required (or set [reviewer] name in qc.config.toml)",
            file=sys.stderr,
        )
        return 2

    rows = conn.execute(
        "SELECT id, pdf_path, toc_start, toc_end FROM spec_volumes ORDER BY id"
    ).fetchall()

    total_emitted = 0
    total_unmatched = 0
    for row in rows:
        pdf_path = Path(row["pdf_path"])
        fmt = emit_mod.detect_section_format(
            pdf_path, int(row["toc_start"]), int(row["toc_end"] or row["toc_start"])
        )
        manifest = emit_mod.build_manifest(conn, row["id"], section_format=fmt)
        print(f"volume {row['id']}: detected section format = '{fmt}'")
        result = emit_mod.emit_to_pdf(
            pdf_path, manifest, reviewer=reviewer, in_place=args.in_place
        )
        total_emitted += result.emitted
        total_unmatched += len(result.unmatched)
        print(
            f"volume {row['id']}: {result.emitted} emitted, "
            f"{len(result.unmatched)} unmatched -> {result.output_path}"
        )
        for entry in result.unmatched:
            print(
                f"  unmatched: {entry['subject']} p.{entry['page']} "
                f"terms={entry.get('search_terms')}"
            )

    print(f"TOTAL: {total_emitted} emitted, {total_unmatched} unmatched")
    return 0 if total_unmatched == 0 else 1


def spec_check_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Spec check via qc.sqlite (preview or emit).")
    parser.add_argument("project_folder", help="Folder containing spec PDF(s) and qc.sqlite")
    parser.add_argument(
        "--mode",
        choices=["preview", "emit"],
        default="preview",
        help="preview: print findings; emit: write annotated PDF via PyMuPDF (ADR-0012)",
    )
    parser.add_argument(
        "--reviewer",
        help="Author name to set on emitted annotations (required for --mode=emit)",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the source PDF instead of writing <name>.marked.pdf",
    )
    args = parser.parse_args(argv)

    if indexer.needs_reindex(args.project_folder):
        print("qc.sqlite missing or stale — running index...")
        indexer.index_project(args.project_folder)

    conn = queries.open_project_db(args.project_folder)
    try:
        if args.mode == "emit":
            return _emit(conn, args)
        findings = queries.all_findings(conn)
    finally:
        conn.close()

    by_kind: dict[str, list[dict]] = defaultdict(list)
    for row in findings:
        by_kind[row["kind"]].append(row)

    print(f"=== spec-check preview ({Path(args.project_folder).name}) ===")
    print(f"Total findings: {len(findings)}\n")

    for kind in SPEC_FINDING_KINDS:
        rows = by_kind.get(kind, [])
        if not rows:
            continue
        emit_count = sum(1 for r in rows if r["expected_action"] == "emit_markup")
        print(f"## {kind} ({len(rows)} rows, {emit_count} emit_markup)")
        for row in rows[:50]:
            print(_format_finding(row))
        if len(rows) > 50:
            print(f"  ... and {len(rows) - 50} more")
        print()

    return 0


def _drawing_emit(conn, args) -> int:
    reviewer = args.reviewer or _load_reviewer_from_config(Path(args.project_folder))
    if not reviewer:
        print(
            "ERROR: --reviewer required (or set [reviewer] name in qc.config.toml)",
            file=sys.stderr,
        )
        return 2

    rows = conn.execute(
        "SELECT id, pdf_path FROM drawing_volumes ORDER BY id"
    ).fetchall()

    total_emitted = 0
    total_skipped = 0
    total_unmatched = 0
    for row in rows:
        manifest = drawing_emit.build_manifest(conn, row["id"])
        if not manifest:
            continue
        pdf_path = Path(row["pdf_path"])
        result = drawing_emit.emit_to_pdf(
            pdf_path, manifest, reviewer=reviewer, in_place=args.in_place
        )
        total_emitted += result.emitted
        total_skipped += result.skipped_existing
        total_unmatched += len(result.unmatched)
        print(
            f"volume {row['id']}: {result.emitted} emitted, "
            f"{result.skipped_existing} skipped, "
            f"{len(result.unmatched)} unmatched -> {result.output_path}"
        )
        for entry in result.unmatched:
            print(
                f"  unmatched: {entry['subject']} p.{entry['page']} "
                f"terms={entry.get('search_terms')}"
            )

    print(
        f"TOTAL: {total_emitted} emitted, {total_skipped} skipped, "
        f"{total_unmatched} unmatched"
    )
    return 0


def drawing_index_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Drawing index QC via qc.sqlite (preview or emit)."
    )
    parser.add_argument("project_folder", help="Folder containing drawing PDF(s)")
    parser.add_argument(
        "--mode",
        choices=["preview", "emit"],
        default="preview",
        help="preview: print findings; emit: write annotated PDF via PyMuPDF (ADR-0012)",
    )
    parser.add_argument(
        "--reviewer",
        help="Author name to set on emitted annotations (required for --mode=emit)",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the source PDF instead of writing <name>.marked.pdf",
    )
    args = parser.parse_args(argv)

    if _needs_full_index(args.project_folder):
        print("qc.sqlite missing or stale — running qc-index...")
        _run_qc_index(args.project_folder)

    conn = drawing_queries.open_project_db(args.project_folder)
    try:
        if args.mode == "emit":
            return _drawing_emit(conn, args)
        findings = drawing_queries.all_findings(conn)
    finally:
        conn.close()

    by_kind: dict[str, list[dict]] = defaultdict(list)
    for row in findings:
        by_kind[row["kind"]].append(row)

    print(f"=== drawing-index-qc preview ({Path(args.project_folder).name}) ===")
    print(f"Total findings: {len(findings)}\n")

    for kind in DRAWING_FINDING_KINDS:
        rows = by_kind.get(kind, [])
        if not rows:
            continue
        emit_count = sum(1 for r in rows if r["expected_action"] == "emit_markup")
        print(f"## {kind} ({len(rows)} rows, {emit_count} emit_markup)")
        for row in rows[:50]:
            print(_format_drawing_finding(row))
        if len(rows) > 50:
            print(f"  ... and {len(rows) - 50} more")
        print()

    return 0
