"""CLI entry points: qc-index, spec-check, and drawing-index-qc (all PyMuPDF emit, ADR-0012)."""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

from qc_core.discovery import discover_all_pdfs, qc_sqlite_path
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


def _feedback_report_main(argv: list[str] | None = None) -> int:
    from qc_core.feedback_report import main as _main

    return _main(argv)


COMMANDS = {
    "qc-index": lambda argv: qc_index_main(argv),
    "spec-check": lambda argv: spec_check_main(argv),
    "spec-check-mcp": lambda argv: spec_check_main(argv),  # deprecated alias (ADR-0012)
    "drawing-index-qc": lambda argv: drawing_index_main(argv),
    "door-check": lambda argv: door_check_main(argv),
    "report-issue": lambda argv: _feedback_report_main(argv),
}


def main(argv: list[str] | None = None) -> int:
    """Dispatch ``python -m qc_core.cli <command> ...`` (docs/agents/dev-mode.md)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python -m qc_core.cli <command> [args...]", file=sys.stderr)
        print("commands: " + ", ".join(COMMANDS), file=sys.stderr)
        return 2
    if argv[0] in ("-h", "--help"):
        print("usage: python -m qc_core.cli <command> [args...]")
        print("commands: " + ", ".join(COMMANDS))
        return 0
    command, rest = argv[0], argv[1:]
    handler = COMMANDS.get(command)
    if handler is None:
        print(f"unknown command: {command}", file=sys.stderr)
        print("commands: " + ", ".join(COMMANDS), file=sys.stderr)
        return 2
    return handler(rest)


# Default reviewer when neither --reviewer nor qc.config.toml supplies one.
# Interim convenience until per-reviewer config is the norm.
DEFAULT_REVIEWER = "REDICHECK-TKN"


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


def _resolve_reviewer(args) -> str:
    """CLI flag > qc.config.toml > DEFAULT_REVIEWER."""
    return (
        args.reviewer
        or _load_reviewer_from_config(Path(args.project_folder))
        or DEFAULT_REVIEWER
    )



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

    discovery = discover_all_pdfs(project_folder)
    print(
        f"discovery: {discovery.spec_count} spec / {discovery.drawing_count} drawing / "
        f"{len(discovery.other)} other"
    )
    for entry in discovery.other:
        print(f"  other: {entry.path.name} — {entry.reason}")

    if discovery.other and discovery.drawing_count == 0:
        print()
        print("!! UNTRUSTED SCOPE (ADR-0026) — possible drawing coverage gap:")
        print(
            f"  {len(discovery.other)} non-spec PDF(s) classified 'other' and "
            "0 drawing volumes discovered — indexing may have silently skipped "
            "real drawing content."
        )
        print("  Review the 'other' filenames above before treating this run as clean.\n")

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
    reviewer = _resolve_reviewer(args)
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
            reviewer=reviewer,
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
        help="preview: grouped door findings; emit: red FreeText callouts via PyMuPDF (ADR-0012)",
    )
    parser.add_argument(
        "--reviewer",
        help=(
            "Author name on emitted annotations "
            f"(default: qc.config.toml [reviewer] name, else {DEFAULT_REVIEWER})"
        ),
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
    if kind == "embedded_report_present":
        return (
            f"  [info] {row['section']} — {row.get('title') or ''} "
            f"(TOC p.{row.get('toc_page')}, report p.{row.get('body_page')}) "
            f"[embedded non-CSI report, present]"
        )
    if kind == "title_mismatch_across_volumes":
        return (
            f"  [{row.get('severity', 'low')}] {row['section']} — "
            f"{row.get('title') or ''} (TOC p.{row.get('toc_page')}) "
            f"{row.get('notes') or ''}"
        ).rstrip()
    if kind == "section_number_mismatch":
        return (
            f"  [{row.get('severity', 'high')}] {row['section']} should be "
            f"{row.get('probable_match')} — {row.get('title') or ''} "
            f"(body p.{row.get('body_page')}, TOC p.{row.get('toc_page')})"
        ).rstrip()
    if kind == "spec_toc_absent":
        return f"  [info] {row.get('notes') or 'No specification TOC found.'}"
    if kind == "incomplete_placeholder":
        return (
            f"  [{row.get('severity', 'medium')}] p.{row.get('body_page')} "
            f"\"{row.get('client_comment') or ''}\" — {row.get('context') or ''}"
        ).rstrip()
    if kind in ("duplicate_section_number", "duplicate_section_number_and_name"):
        return (
            f"  [{row.get('severity', 'medium')}] {row['section']} "
            f"(TOC p.{row.get('toc_page')}) {row.get('notes') or ''}"
        ).rstrip()
    return f"  {kind}: {row}"


def _spec_matrix_report(conn) -> int:
    """Print the spec judgment-node worklist as JSON (ADR-0026): tripped
    invariants, pending Evidence findings, and disputed matrix rows."""
    import json as _json

    from qc_core.spec import matrix as spec_matrix

    report = {
        "check": spec_matrix.CHECK_NAME,
        "invariants": spec_matrix.all_invariants(conn),
        "pending_evidence": spec_matrix.pending_evidence(conn),
        "disputed_rows": spec_matrix.disputed_rows(conn),
    }
    print(_json.dumps(report, indent=2))
    return 0


def _spec_apply_judgments(conn, path: str) -> int:
    import json as _json

    from qc_core.spec import matrix as spec_matrix

    payload = _json.loads(Path(path).read_text(encoding="utf-8"))
    applied = spec_matrix.apply_judgments(conn, payload)
    conn.commit()
    print(
        f"judgments applied: {applied['promoted']} promoted, "
        f"{applied['dismissed']} dismissed, {applied['reclassified']} reclassified, "
        f"{applied['invariants']} invariant resolutions"
    )
    return 0


def _spec_trust_gate(conn) -> list[str]:
    """ADR-0026 §6a teeth: reasons emit must not proceed, empty when clean."""
    from qc_core.spec import matrix as spec_matrix

    problems = []
    for inv in spec_matrix.all_invariants(conn):
        if inv["status"] == "tripped":
            problems.append(
                f"tripped invariant [{inv['id']}] {inv['invariant']} scope={inv['scope']}"
            )
    pending = spec_matrix.pending_evidence(conn)
    if pending:
        problems.append(f"{len(pending)} finding(s) at status=evidence pending judgment")
    return problems


def _emit(conn, args) -> int:
    problems = _spec_trust_gate(conn)
    if problems:
        print("EMIT BLOCKED — output is untrusted until resolved (ADR-0026):")
        for p in problems:
            print(f"  - {p}")
        print(
            "Run --mode=matrix for the judgment worklist, then "
            "--apply-judgments <decisions.json>, or record a Reviewer override."
        )
        return 2

    reviewer = _resolve_reviewer(args)
    kinds = args.kind or None

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
        manifest = emit_mod.build_manifest(
            conn, row["id"], section_format=fmt, kinds=kinds
        )
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
        choices=["preview", "emit", "matrix"],
        default="preview",
        help=(
            "preview: print findings; emit: write annotated PDF via PyMuPDF "
            "(ADR-0012); matrix: print the judgment-node worklist as JSON "
            "(tripped invariants, pending evidence, disputed matrix rows; ADR-0026)"
        ),
    )
    parser.add_argument(
        "--apply-judgments",
        metavar="DECISIONS_JSON",
        help=(
            "Apply a judgment node's decisions file (promote/dismiss/reclassify "
            "evidence; resolve/override invariants) per ADR-0026, then exit"
        ),
    )
    parser.add_argument(
        "--reviewer",
        help=(
            "Author name on emitted annotations "
            f"(default: qc.config.toml [reviewer] name, else {DEFAULT_REVIEWER})"
        ),
    )
    parser.add_argument(
        "--kind",
        action="append",
        choices=SPEC_FINDING_KINDS,
        metavar="KIND",
        help=(
            "Restrict emit to this finding kind (repeatable). "
            "Omit to emit all kinds. Choices: " + ", ".join(SPEC_FINDING_KINDS)
        ),
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
        if args.apply_judgments:
            return _spec_apply_judgments(conn, args.apply_judgments)
        if args.mode == "matrix":
            return _spec_matrix_report(conn)
        if args.mode == "emit":
            return _emit(conn, args)
        findings = queries.all_findings(conn)
        gate_problems = _spec_trust_gate(conn)
    finally:
        conn.close()

    by_kind: dict[str, list[dict]] = defaultdict(list)
    for row in findings:
        by_kind[row["kind"]].append(row)

    print(f"=== spec-check preview ({Path(args.project_folder).name}) ===")
    print(f"Total findings: {len(findings)}\n")

    if gate_problems:
        print("!! UNTRUSTED SCOPE (ADR-0026) — emit is blocked until resolved:")
        for p in gate_problems:
            print(f"  - {p}")
        print("  Run --mode=matrix for the judgment worklist.\n")

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


def _render_scoreboard(scoreboard: list[dict]) -> str:
    """Format scoreboard as an aligned text table."""
    header = (
        f"{'PREFIX':<8}  {'INDEX':>6}  {'BMKS':>6}  {'RECNC':>6}  {'DISP':>6}  {'ANOM':>5}  NOTE"
    )
    lines = [header, "-" * len(header)]
    for row in scoreboard:
        flag = " !" if row.get("zero_reconciled") else "  "
        lines.append(
            f"{row['prefix']:<8}{flag}  "
            f"{row['index_count']:>6}  "
            f"{row['bookmark_count']:>6}  "
            f"{row['reconciled']:>6}  "
            f"{row['disputed']:>6}  "
            f"{row['anomalies']:>5}"
        )
    return "\n".join(lines)


def _drawing_matrix_report(conn) -> int:
    """Print the judgment-node worklist as JSON (ADR-0026): tripped
    invariants, pending Evidence findings, disputed matrix rows, and
    per-prefix scoreboard."""
    import json as _json

    from qc_core.drawing import matrix as drawing_matrix

    report = {
        "check": drawing_matrix.CHECK_NAME,
        "invariants": drawing_matrix.all_invariants(conn),
        "pending_evidence": drawing_matrix.pending_evidence(conn),
        "disputed_rows": drawing_matrix.disputed_rows(conn),
        "scoreboard": drawing_matrix.compute_scoreboard(conn),
        "prefix_facts": drawing_matrix.prefix_facts(conn),
        "discipline_index_candidates": drawing_matrix.discipline_index_candidates(conn),
    }
    print(_json.dumps(report, indent=2))
    return 0


def _drawing_sweep_report(conn, as_json: bool) -> int:
    """--mode=sweep: scoreboard for all prefixes + raw dumps for suspicious ones."""
    import json as _json

    from qc_core.drawing import matrix as drawing_matrix

    worklist = drawing_matrix.sweep_worklist(conn)

    if as_json:
        print(_json.dumps(worklist, indent=2))
        return 0

    print("=== completeness sweep ===")
    print(
        "Clean prefixes show as one scoreboard line. "
        "Suspicious prefixes (anomalies/disputes/zero-reconciled/count-mismatch) get full raw dumps.\n"
    )
    header = (
        f"{'PREFIX':<8}  {'INDEX':>6}  {'BMKS':>6}  {'RECNC':>6}  {'DISP':>6}  {'ANOM':>5}  NOTE"
    )
    print(header)
    print("-" * len(header))
    for row in worklist:
        flag = " !" if row.get("zero_reconciled") else "  "
        status = "[suspicious]" if row["suspicious"] else ""
        print(
            f"{row['prefix']:<8}{flag}  "
            f"{row['index_count']:>6}  "
            f"{row['bookmark_count']:>6}  "
            f"{row['reconciled']:>6}  "
            f"{row['disputed']:>6}  "
            f"{row['anomalies']:>5}  {status}"
        )
        if row["suspicious"]:
            idx = row.get("index_rows") or []
            bmk = row.get("bookmark_rows") or []
            anm = row.get("anomaly_rows") or []
            if idx:
                print(f"  index rows ({len(idx)}):")
                for e in idx:
                    print(f"    p.{e['page']:>3}  raw={e['raw']!r}  key={e['key']!r}")
            if bmk:
                print(f"  bookmark rows ({len(bmk)}):")
                for e in bmk:
                    print(f"    p.{e['page']:>3}  raw={e['raw']!r}  key={e['key']!r}")
            if anm:
                print(f"  parse anomalies ({len(anm)}):")
                for e in anm:
                    print(f"    {e['sheet_number']!r}  {e['notes'] or ''}")
            print()
    return 0


def _drawing_apply_judgments(conn, path: str) -> int:
    import json as _json
    import sys as _sys

    from qc_core.drawing import matrix as drawing_matrix

    payload = _json.loads(Path(path).read_text(encoding="utf-8"))
    try:
        applied = drawing_matrix.apply_judgments(conn, payload)
    except ValueError as exc:
        print(f"error: {exc}", file=_sys.stderr)
        return 1
    conn.commit()
    print(
        f"judgments applied: {applied['promoted']} promoted, "
        f"{applied['dismissed']} dismissed, {applied['reclassified']} reclassified, "
        f"{applied['invariants']} invariant resolutions"
    )
    return 0


def _drawing_trust_gate(conn) -> list[str]:
    """ADR-0026 §6a teeth: reasons emit must not proceed, empty when clean."""
    from qc_core.drawing import matrix as drawing_matrix

    problems = []
    tripped = [
        inv for inv in drawing_matrix.all_invariants(conn) if inv["status"] == "tripped"
    ]
    for inv in tripped:
        problems.append(
            f"tripped invariant [{inv['id']}] {inv['invariant']} scope={inv['scope']}"
        )
    pending = drawing_matrix.pending_evidence(conn)
    if pending:
        problems.append(f"{len(pending)} finding(s) at status=evidence pending judgment")
    return problems


def _drawing_emit(conn, args) -> int:
    problems = _drawing_trust_gate(conn)
    if problems:
        print("EMIT BLOCKED — output is untrusted until resolved (ADR-0026):")
        for p in problems:
            print(f"  - {p}")
        print(
            "Run --mode=matrix for the judgment worklist, then "
            "--apply-judgments <decisions.json>, or record a Reviewer override."
        )
        return 2

    reviewer = _resolve_reviewer(args)
    kinds = args.kind or None

    rows = conn.execute(
        "SELECT id, pdf_path FROM drawing_volumes ORDER BY id"
    ).fetchall()

    total_emitted = 0
    total_skipped = 0
    total_unmatched = 0
    for row in rows:
        manifest = drawing_emit.build_manifest(conn, row["id"], kinds=kinds)
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


# ---------------------------------------------------------------------------
# Read-only inspection helpers (--show-index / --show-bookmarks / --explain)
# ---------------------------------------------------------------------------


def _inspect_show_index(conn, volume: int | None, as_json: bool) -> int:
    """Print parsed index rows from drawing_index_entries."""
    import json as _json

    from qc_core.drawing.parse import normalize_sheet_number

    query = (
        "SELECT e.volume_id, e.sheet_number, e.title, e.source, e.index_page "
        "FROM drawing_index_entries e "
    )
    params: list = []
    if volume is not None:
        query += "WHERE e.volume_id = ? "
        params.append(volume)
    query += "ORDER BY e.volume_id, e.index_page, e.sheet_number"

    rows = conn.execute(query, params).fetchall()

    if as_json:
        out = [
            {
                "volume_id": r["volume_id"],
                "raw_value": r["sheet_number"],
                "normalized_key": normalize_sheet_number(r["sheet_number"]),
                "title": r["title"],
                "source": r["source"],
                "index_page": r["index_page"],
            }
            for r in rows
        ]
        print(_json.dumps(out, indent=2))
        return 0

    print(f"drawing_index_entries ({len(rows)} rows)")
    for r in rows:
        norm = normalize_sheet_number(r["sheet_number"])
        raw = r["sheet_number"]
        arrow = f"{raw!r} -> {norm!r}" if raw != norm else repr(raw)
        print(
            f"  vol={r['volume_id']} p.{r['index_page']:>3}  {arrow}"
            f"  [{r['source']}]"
            + (f"  title={r['title']!r}" if r["title"] else "")
        )
    return 0


def _inspect_show_bookmarks(conn, discipline: str | None, as_json: bool) -> int:
    """Print sheet catalog from drawing_sheets (bookmark channel)."""
    import json as _json

    from qc_core.drawing.parse import normalize_sheet_number

    query = (
        "SELECT s.volume_id, s.sheet_number, s.title, s.page "
        "FROM drawing_sheets s "
    )
    params: list = []
    if discipline is not None:
        query += "WHERE upper(s.sheet_number) LIKE upper(?) "
        params.append(f"{discipline}%")
    query += "ORDER BY s.volume_id, s.page, s.sheet_number"

    rows = conn.execute(query, params).fetchall()

    if as_json:
        out = [
            {
                "volume_id": r["volume_id"],
                "raw_value": r["sheet_number"],
                "normalized_key": normalize_sheet_number(r["sheet_number"]),
                "title": r["title"],
                "page": r["page"],
                "discipline": (r["sheet_number"] or "")[:1].upper() or None,
            }
            for r in rows
        ]
        print(_json.dumps(out, indent=2))
        return 0

    print(f"drawing_sheets / bookmarks ({len(rows)} rows)")
    for r in rows:
        norm = normalize_sheet_number(r["sheet_number"])
        raw = r["sheet_number"]
        arrow = f"{raw!r} -> {norm!r}" if raw != norm else repr(raw)
        disc = (raw or "")[:1].upper() or "?"
        print(
            f"  vol={r['volume_id']} p.{r['page']:>3}  {arrow}"
            f"  disc={disc}"
            + (f"  title={r['title']!r}" if r["title"] else "")
        )
    return 0


def _inspect_explain(conn, sheet: str, as_json: bool) -> int:
    """Show one key across every channel: matrix rows, findings, invariants."""
    import json as _json

    from qc_core.drawing.parse import normalize_sheet_number
    from qc_core.drawing.matrix import CHECK_NAME

    key = normalize_sheet_number(sheet)

    matrix_rows = conn.execute(
        "SELECT channel, raw_value, page, detail "
        "FROM reconciliation_matrix "
        "WHERE check_name = ? AND entity_key = ? "
        "ORDER BY channel, page",
        (CHECK_NAME, key),
    ).fetchall()

    findings_rows = conn.execute(
        "SELECT kind, status, judgment_rationale "
        "FROM findings "
        "WHERE sheet_number = ? OR sheet_number = ? "
        "ORDER BY kind",
        (key, sheet),
    ).fetchall()

    # Invariants whose scope is a prefix of this key
    prefix = key[:1].upper() if key else ""
    invariant_rows = conn.execute(
        "SELECT invariant, scope, status, rationale "
        "FROM invariant_results "
        "WHERE check_name = ? AND scope = ? "
        "ORDER BY invariant",
        (CHECK_NAME, prefix),
    ).fetchall() if prefix else []

    if as_json:
        out = {
            "sheet": sheet,
            "normalized_key": key,
            "matrix": [
                {
                    "channel": r["channel"],
                    "raw_value": r["raw_value"],
                    "page": r["page"],
                    "detail": _json.loads(r["detail"]) if r["detail"] else None,
                }
                for r in matrix_rows
            ],
            "findings": [
                {
                    "kind": r["kind"],
                    "status": r["status"],
                    "judgment_rationale": r["judgment_rationale"],
                }
                for r in findings_rows
            ],
            "invariants": [
                {
                    "invariant": r["invariant"],
                    "scope": r["scope"],
                    "status": r["status"],
                    "rationale": r["rationale"],
                }
                for r in invariant_rows
            ],
        }
        print(_json.dumps(out, indent=2))
        return 0

    print(f"=== explain {sheet!r}  (normalized: {key!r}) ===")
    print(f"\nMatrix channels ({len(matrix_rows)} rows):")
    if matrix_rows:
        for r in matrix_rows:
            detail = f"  detail={r['detail']}" if r["detail"] else ""
            print(f"  [{r['channel']}]  raw={r['raw_value']!r}  p.{r['page']}{detail}")
    else:
        print("  (no matrix rows — key not yet indexed)")

    print(f"\nFindings ({len(findings_rows)} rows):")
    if findings_rows:
        for r in findings_rows:
            rat = f"  rationale={r['judgment_rationale']!r}" if r["judgment_rationale"] else ""
            print(f"  kind={r['kind']}  status={r['status']}{rat}")
    else:
        print("  (none)")

    if invariant_rows:
        print(f"\nInvariants covering prefix {prefix!r}:")
        for r in invariant_rows:
            rat = f"  rationale={r['rationale']!r}" if r["rationale"] else ""
            print(f"  {r['invariant']}  scope={r['scope']}  status={r['status']}{rat}")

    return 0


def drawing_index_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Drawing index QC via qc.sqlite (preview or emit)."
    )
    parser.add_argument("project_folder", help="Folder containing drawing PDF(s)")
    parser.add_argument(
        "--mode",
        choices=["preview", "emit", "matrix", "sweep"],
        default="preview",
        help=(
            "preview: print findings with scoreboard; emit: write annotated PDF via PyMuPDF "
            "(ADR-0012); matrix: print the judgment-node worklist as JSON "
            "(tripped invariants, pending evidence, disputed matrix rows, scoreboard; ADR-0026); "
            "sweep: completeness sweep worklist — scoreboard for all prefixes + raw side-by-side "
            "dumps for suspicious ones (ADR-0027)"
        ),
    )
    parser.add_argument(
        "--apply-judgments",
        metavar="DECISIONS_JSON",
        help=(
            "Apply a judgment node's decisions file (promote/dismiss/reclassify "
            "evidence; resolve/override invariants) per ADR-0026, then exit"
        ),
    )
    parser.add_argument(
        "--reviewer",
        help=(
            "Author name on emitted annotations "
            f"(default: qc.config.toml [reviewer] name, else {DEFAULT_REVIEWER})"
        ),
    )
    parser.add_argument(
        "--kind",
        action="append",
        choices=DRAWING_FINDING_KINDS,
        metavar="KIND",
        help=(
            "Restrict emit to this finding kind (repeatable). "
            "Omit to emit all kinds. Choices: " + ", ".join(DRAWING_FINDING_KINDS)
        ),
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the source PDF instead of writing <name>.marked.pdf",
    )
    # Read-only inspection flags (ADR-0027 / issue #68)
    parser.add_argument(
        "--show-index",
        action="store_true",
        help=(
            "Print parsed index rows from drawing_index_entries "
            "(raw value -> normalized key, source, page). Read-only."
        ),
    )
    parser.add_argument(
        "--volume",
        type=int,
        metavar="N",
        help="Filter --show-index to volume N.",
    )
    parser.add_argument(
        "--show-bookmarks",
        action="store_true",
        help=(
            "Print sheet catalog from drawing_sheets (bookmark channel): "
            "raw title -> normalized key, page, discipline. Read-only."
        ),
    )
    parser.add_argument(
        "--discipline",
        metavar="PREFIX",
        help="Filter --show-bookmarks to sheets whose number starts with PREFIX.",
    )
    parser.add_argument(
        "--explain",
        metavar="SHEET",
        help=(
            "Show one key across every channel: matrix rows, findings, invariants "
            "covering that prefix. Accepts raw or normalized sheet number. Read-only."
        ),
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON (all inspection commands).",
    )
    args = parser.parse_args(argv)

    # Inspection commands are read-only; skip the stale-index check so they
    # work even when invariants are tripped and emit is blocked.
    is_inspect = args.show_index or args.show_bookmarks or bool(args.explain)

    if not is_inspect and _needs_full_index(args.project_folder):
        print("qc.sqlite missing or stale — running qc-index...")
        _run_qc_index(args.project_folder)

    conn = drawing_queries.open_project_db(args.project_folder)
    try:
        if args.show_index:
            return _inspect_show_index(conn, args.volume, args.as_json)
        if args.show_bookmarks:
            return _inspect_show_bookmarks(conn, args.discipline, args.as_json)
        if args.explain:
            return _inspect_explain(conn, args.explain, args.as_json)
        if args.apply_judgments:
            return _drawing_apply_judgments(conn, args.apply_judgments)
        if args.mode == "matrix":
            return _drawing_matrix_report(conn)
        if args.mode == "sweep" or getattr(args, "sweep", False):
            return _drawing_sweep_report(conn, args.as_json)
        if args.mode == "emit":
            return _drawing_emit(conn, args)
        findings = drawing_queries.all_findings(conn)
        gate_problems = _drawing_trust_gate(conn)
        from qc_core.drawing import matrix as drawing_matrix
        scoreboard = drawing_matrix.compute_scoreboard(conn)
    finally:
        conn.close()

    by_kind: dict[str, list[dict]] = defaultdict(list)
    for row in findings:
        by_kind[row["kind"]].append(row)

    print(f"=== drawing-index-qc preview ({Path(args.project_folder).name}) ===")
    print(f"Total findings: {len(findings)}\n")

    # Scoreboard at top of preview (Part 2)
    if scoreboard:
        print(_render_scoreboard(scoreboard))
        print()

    if gate_problems:
        print("!! UNTRUSTED SCOPE (ADR-0026) — emit is blocked until resolved:")
        for p in gate_problems:
            print(f"  - {p}")
        print("  Run --mode=matrix for the judgment worklist.\n")

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


if __name__ == "__main__":
    sys.exit(main())
