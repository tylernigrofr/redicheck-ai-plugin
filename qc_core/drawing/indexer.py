"""Write drawing extraction results into qc.sqlite and populate findings (ADR-0014)."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from qc_core.db import init_db
from qc_core.drawing.kinds import DRAWING_FINDING_KINDS
from qc_core.drawing.config import load_drawing_config
from qc_core.drawing.discipline import infer_sheet_discipline
from qc_core.drawing.parse import _prefixes, analyze_pdf, normalize_sheet_number


def _discipline_from_filename(path: Path) -> str | None:
    stem = path.stem
    stem = re.sub(r"^\d{2}\s+", "", stem)
    return stem.strip() or None


_AREA_SUFFIX_RE = re.compile(r"^(.*\d)\.([A-Z])$")


def _index_covers(set_key: str, index_keys: set[str]) -> bool:
    """True if the set's sheet number is covered by the index.

    Direct match is always coverage. An area-suffix split (e.g. AD101.A, A101.B)
    is covered when the base sheet (AD101, A101) is listed in the index — a
    common architectural documentation convention where one index row stands
    for both area halves. Without this, every .A/.B pair fires a false
    sheet_in_set_not_in_index.
    """
    if set_key in index_keys:
        return True
    m = _AREA_SUFFIX_RE.match(set_key)
    if m and m.group(1) in index_keys:
        return True
    return False


def index_drawing_pdf(
    conn: sqlite3.Connection,
    pdf_path: str | Path,
    *,
    force: bool = False,
    config=None,
    project_bookmark_prefixes: set[str] | None = None,
    project_sheet_keys: set[str] | None = None,
) -> dict:
    """Parse one drawing PDF into drawing_volumes, sheets, and index entries."""
    from qc_core.discovery import drawing_set_pattern

    path = Path(pdf_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Drawing PDF not found: {path}")

    if config is None:
        config = load_drawing_config(path.parent)

    mtime = path.stat().st_mtime
    existing = conn.execute(
        "SELECT id, pdf_mtime FROM drawing_volumes WHERE pdf_path = ?",
        (str(path),),
    ).fetchone()

    if existing and not force and abs(existing["pdf_mtime"] - mtime) < 0.001:
        return {
            "indexed": False,
            "reason": "unchanged",
            "volume_id": existing["id"],
            "pdf_path": str(path),
        }

    result = analyze_pdf(
        path,
        config=config,
        project_bookmark_prefixes=project_bookmark_prefixes,
        project_sheet_keys=project_sheet_keys,
    )
    if not result.get("success"):
        raise RuntimeError(result.get("error", "Drawing PDF analysis failed"))

    meta = result["meta"]
    pattern = drawing_set_pattern(path)
    discipline = _discipline_from_filename(path)

    if existing:
        volume_id = existing["id"]
        conn.execute("DELETE FROM drawing_sheets WHERE volume_id = ?", (volume_id,))
        conn.execute("DELETE FROM drawing_index_entries WHERE volume_id = ?", (volume_id,))
        conn.execute("DELETE FROM drawing_parse_anomalies WHERE volume_id = ?", (volume_id,))
        conn.execute(
            """
            UPDATE drawing_volumes
            SET pdf_mtime = ?, page_count = ?, discipline = ?, set_pattern = ?,
                indexed_at = datetime('now')
            WHERE id = ?
            """,
            (mtime, meta["total_pages"], discipline, pattern, volume_id),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO drawing_volumes (
                pdf_path, pdf_mtime, page_count, discipline, set_pattern
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (str(path), mtime, meta["total_pages"], discipline, pattern),
        )
        volume_id = cur.lastrowid

    for sheet in result["sheets"]:
        inf = infer_sheet_discipline(
            sheet["sheet_number"],
            sheet.get("title"),
            volume_discipline_hint=discipline,
        )
        conn.execute(
            """
            INSERT INTO drawing_sheets (
                volume_id, sheet_number, title, page, confidence, discipline
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                volume_id,
                sheet["sheet_number"],
                sheet.get("title"),
                sheet["page"],
                sheet.get("confidence"),
                inf.discipline,
            ),
        )

    for entry in result["index_entries"]:
        conn.execute(
            """
            INSERT INTO drawing_index_entries (
                volume_id, sheet_number, title, source, index_page
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                volume_id,
                entry["sheet_number"],
                entry.get("title"),
                entry["source"],
                entry.get("index_page"),
            ),
        )

    import json as _json

    for anom in result.get("bookmark_anomalies", []):
        conn.execute(
            "INSERT INTO drawing_parse_anomalies (volume_id, channel, raw_text, page, detail) "
            "VALUES (?, 'bookmarks', ?, ?, ?)",
            (volume_id, anom["raw"], anom.get("page"),
             _json.dumps({k: v for k, v in anom.items() if k not in ("raw", "page")})),
        )

    for anom in result.get("index_anomalies", []):
        channel = anom.get("channel", "volume_index")
        conn.execute(
            "INSERT INTO drawing_parse_anomalies (volume_id, channel, raw_text, page, detail) "
            "VALUES (?, ?, ?, ?, ?)",
            (volume_id, channel, anom["raw"], anom.get("page"),
             _json.dumps({k: v for k, v in anom.items() if k not in ("raw", "page", "channel")})),
        )

    return {
        "indexed": True,
        "volume_id": volume_id,
        "pdf_path": str(path),
        "sheets": len(result["sheets"]),
        "index_entries": len(result["index_entries"]),
        "bookmark_anomalies": len(result.get("bookmark_anomalies", [])),
        "index_anomalies": len(result.get("index_anomalies", [])),
        "meta": meta,
        "titleblock_mismatches": result.get("titleblock_mismatches", []),
        "bookmark_parse_warning": meta.get("bookmark_parse_warning"),
    }


def _clear_drawing_findings(conn: sqlite3.Connection) -> None:
    placeholders = ",".join("?" * len(DRAWING_FINDING_KINDS))
    conn.execute(
        f"DELETE FROM findings WHERE kind IN ({placeholders})",
        DRAWING_FINDING_KINDS,
    )


def _insert_finding(
    conn: sqlite3.Connection,
    *,
    kind: str,
    sheet_number: str,
    drawing_volume_id: int | None = None,
    title: str | None = None,
    source_page: int | None = None,
    notes: str | None = None,
    expected_action: str = "emit_markup",
) -> None:
    conn.execute(
        """
        INSERT INTO findings (
            drawing_volume_id, kind, expected_action, severity,
            sheet_number, title, source_page, notes, evidence_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            drawing_volume_id,
            kind,
            expected_action,
            _severity_for_kind(kind),
            sheet_number,
            title,
            source_page,
            notes,
            normalize_sheet_number(sheet_number) if sheet_number else None,
        ),
    )


def _severity_for_kind(kind: str) -> str:
    if kind in ("sheet_in_index_not_in_set", "duplicate_sheet_number"):
        return "high"
    if kind == "sheet_number_mismatch":
        return "medium"
    if kind == "sheet_discipline_reviewer_resolution":
        return "low"
    return "medium"


def _emit_sheet_discipline_review_findings(conn: sqlite3.Connection) -> None:
    """ADR-0023: surfaced checkpoints when inference is ambiguous."""
    rows = conn.execute(
        """
        SELECT ds.volume_id, ds.sheet_number, ds.title, dv.discipline AS vol_disc
        FROM drawing_sheets ds
        JOIN drawing_volumes dv ON dv.id = ds.volume_id
        """
    ).fetchall()
    for row in rows:
        meta = infer_sheet_discipline(
            row["sheet_number"],
            row["title"],
            volume_discipline_hint=row["vol_disc"],
        )
        if meta.needs_resolution:
            _insert_finding(
                conn,
                kind="sheet_discipline_reviewer_resolution",
                sheet_number=row["sheet_number"],
                drawing_volume_id=row["volume_id"],
                title=row["title"],
                notes=meta.rationale,
                expected_action="info_only",
            )


def _emit_parse_anomaly_findings(conn: sqlite3.Connection) -> None:
    """Insert parse_anomaly findings from drawing_parse_anomalies (ADR-0027, issue #65).

    Each raw extraction failure becomes a finding at status='evidence' with
    expected_action='info_only'.  The raw source text is stored in notes;
    the channel is stored in context.  Since _clear_drawing_findings deletes
    all drawing findings before each recompute, these rows are rebuilt fresh
    on every run — idempotency is guaranteed by the delete-then-reinsert cycle.

    Anomaly findings are deliberately held at status='evidence' so the emit
    gate blocks until they are judged via --apply-judgments.  The typical
    judgment action is 'promote' (keeping them as info markers) or 'dismiss'
    (noise, e.g. a page header that looks like a near-miss).
    """
    rows = conn.execute(
        "SELECT volume_id, channel, raw_text, page FROM drawing_parse_anomalies "
        "ORDER BY volume_id, channel, id"
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            INSERT INTO findings (
                drawing_volume_id, kind, expected_action, severity,
                sheet_number, source_page, notes, context, status, evidence_key
            ) VALUES (?, 'parse_anomaly', 'info_only', 'low', NULL, ?, ?, ?, 'evidence', ?)
            """,
            (
                row["volume_id"],
                row["page"],
                row["raw_text"],
                f"channel={row['channel']}",
                f"parse_anomaly:{row['volume_id']}:{row['channel']}:{row['raw_text'][:80]}",
            ),
        )


def compute_drawing_findings(conn: sqlite3.Connection) -> None:
    """Project-level cross-ref: index vs bookmark catalog (ADR-0014).

    ADR-0026: the channel data is first persisted as the reconciliation
    matrix and the fail-loud invariants are evaluated over it. The set
    algebra below is the deterministic baseline verdict; findings on scopes
    with a tripped, unresolved invariant are held at status='evidence'
    (pending judgment) instead of concluding as Candidates.
    """
    from qc_core.drawing import matrix as drawing_matrix

    _clear_drawing_findings(conn)
    drawing_matrix.build_matrix(conn)
    drawing_matrix.evaluate_invariants(conn)

    volumes = {
        r["id"]: r["pdf_path"]
        for r in conn.execute(
            "SELECT id, pdf_path FROM drawing_volumes ORDER BY id"
        ).fetchall()
    }

    # Detect duplicate sheet numbers in the bookmark catalog before building the
    # deduped dict.  Two bookmarks with the same normalized number in one volume
    # mean the set physically contains a sheet whose number was used twice (e.g.
    # two `E. 304` pages where one should be `E. 305`).
    #
    # Guard: a key collision is only a duplicate-sheet finding when corroborated
    # — either the index lists the key exactly once (two physical pages claim an
    # indexed number: Elk Grove 'E. 304'), or every colliding bookmark carries
    # the identical title (a duplicated/corrupt TOC entry: Elk Grove 'C4' twice,
    # one pointing at the cover page).  Sets whose bookmark numbering splits
    # across the number/title fields (Quarry Oaks MEP: sheet 'E-1', titles
    # '01 - ...', '02 - ...') produce mass collisions ('E1' x38) with differing
    # titles and no matching index key — channel noise that belongs to
    # reconciliation, not this check.  A genuine duplicate that fails both
    # corroborations still surfaces as sheet_in_set_not_in_index.
    _index_key_counts: dict[str, int] = {}
    for row in conn.execute("SELECT sheet_number FROM drawing_index_entries").fetchall():
        k = normalize_sheet_number(row["sheet_number"])
        _index_key_counts[k] = _index_key_counts.get(k, 0) + 1
    _bookmark_counts: dict[tuple[int, str], int] = {}
    _bookmark_first: dict[tuple[int, str], dict] = {}
    _bookmark_titles: dict[tuple[int, str], set[str]] = {}
    for row in conn.execute(
        "SELECT volume_id, sheet_number, title, page FROM drawing_sheets"
    ).fetchall():
        key = (row["volume_id"], normalize_sheet_number(row["sheet_number"]))
        _bookmark_counts[key] = _bookmark_counts.get(key, 0) + 1
        _bookmark_first.setdefault(key, dict(row))
        _bookmark_titles.setdefault(key, set()).add((row["title"] or "").strip().upper())
    for (vol_id, _norm_key), count in _bookmark_counts.items():
        corroborated = (
            _index_key_counts.get(_norm_key) == 1
            or len(_bookmark_titles[(vol_id, _norm_key)]) == 1
        )
        if count > 1 and corroborated:
            first = _bookmark_first[(vol_id, _norm_key)]
            _insert_finding(
                conn,
                kind="duplicate_sheet_number",
                sheet_number=first["sheet_number"],
                drawing_volume_id=vol_id,
                source_page=first["page"],
                notes=f"bookmarks x{count}",
            )

    sheets_by_volume: dict[int, dict[str, dict]] = {}
    for row in conn.execute(
        "SELECT volume_id, sheet_number, title, page FROM drawing_sheets"
    ).fetchall():
        key = normalize_sheet_number(row["sheet_number"])
        sheets_by_volume.setdefault(row["volume_id"], {})[key] = dict(row)

    entries_by_volume_source: dict[tuple[int, str], list[dict]] = {}
    for row in conn.execute(
        """
        SELECT volume_id, sheet_number, title, source, index_page
        FROM drawing_index_entries
        ORDER BY volume_id, source, sheet_number
        """
    ).fetchall():
        entries_by_volume_source.setdefault(
            (row["volume_id"], row["source"]), []
        ).append(dict(row))

    project_set: dict[str, dict] = {}
    for vol_id, sheets in sheets_by_volume.items():
        for key, row in sheets.items():
            project_set.setdefault(
                key,
                {
                    "sheet_number": row["sheet_number"],
                    "volume_id": vol_id,
                    "page": row["page"],
                },
            )
    project_prefixes = _prefixes(row["sheet_number"] for row in project_set.values())

    master_entries: list[dict] = []
    for (vol_id, source), entries in entries_by_volume_source.items():
        if source == "master_index":
            master_entries.extend(entries)
    # Project-wide master coverage, available to the per-volume reconciliation
    # below: a sheet listed in the master index is accounted for even if its own
    # discipline sub-index omitted it (e.g. a parse gap on the volume's index
    # page). Without this, such a sheet falsely flags sheet_in_set_not_in_index
    # at the per-volume level despite being present in drawing_index_entries (#39).
    master_keys_all = {
        normalize_sheet_number(e["sheet_number"]) for e in master_entries
    }

    def _flag_duplicates(entries: list[dict], vol_id: int, source_label: str) -> None:
        counts: dict[str, int] = {}
        by_key: dict[str, dict] = {}
        for entry in entries:
            key = normalize_sheet_number(entry["sheet_number"])
            counts[key] = counts.get(key, 0) + 1
            by_key.setdefault(key, entry)
        for key, count in counts.items():
            if count > 1:
                entry = by_key[key]
                _insert_finding(
                    conn,
                    kind="duplicate_sheet_number",
                    sheet_number=entry["sheet_number"],
                    drawing_volume_id=vol_id,
                    source_page=entry.get("index_page"),
                    notes=f"{source_label} x{count}",
                )

    flagged_master_missing: set[str] = set()
    flagged_master_extra: set[str] = set()
    if master_entries:
        master_vol_id = master_entries[0]["volume_id"]
        master_keys = {normalize_sheet_number(e["sheet_number"]) for e in master_entries}
        set_keys = set(project_set.keys())
        for entry in master_entries:
            key = normalize_sheet_number(entry["sheet_number"])
            if key not in set_keys:
                _insert_finding(
                    conn,
                    kind="sheet_in_index_not_in_set",
                    sheet_number=entry["sheet_number"],
                    drawing_volume_id=entry["volume_id"],
                    title=entry.get("title"),
                    source_page=entry.get("index_page"),
                    notes="master_index",
                )
                flagged_master_extra.add(key)
        for key, row in project_set.items():
            if not _index_covers(key, master_keys):
                _insert_finding(
                    conn,
                    kind="sheet_in_set_not_in_index",
                    sheet_number=row["sheet_number"],
                    drawing_volume_id=row["volume_id"],
                    source_page=row["page"],
                    notes="master_index",
                )
                flagged_master_missing.add(key)
        # Per volume: with a sub-set master in play (#54), the same sheet
        # legitimately appears in its own volume's master only — but flagging
        # across the union would mark any main-vs-sub overlap as a duplicate.
        for (vol_id, source), entries in entries_by_volume_source.items():
            if source == "master_index":
                _flag_duplicates(entries, vol_id, "master_index")

    from qc_core.drawing.parse import _SHEET_PREFIX_RE

    for (vol_id, source), entries in entries_by_volume_source.items():
        if source != "volume_index":
            continue
        vol_sheets = sheets_by_volume.get(vol_id, {})
        vol_keys = set(vol_sheets.keys())
        # Filter index parse noise (finish/material/legend codes that look
        # sheet-shaped) by keeping only entries whose prefix matches a real
        # drawing prefix somewhere in the project.
        def _real_sheet(entry: dict) -> bool:
            m = _SHEET_PREFIX_RE.match(entry["sheet_number"])
            if not m:
                return True
            return m.group(1).upper() in project_prefixes
        real_entries = [e for e in entries if _real_sheet(e)]
        index_keys = {normalize_sheet_number(e["sheet_number"]) for e in real_entries}

        for entry in real_entries:
            key = normalize_sheet_number(entry["sheet_number"])
            if key not in vol_keys:
                _insert_finding(
                    conn,
                    kind="sheet_in_index_not_in_set",
                    sheet_number=entry["sheet_number"],
                    drawing_volume_id=vol_id,
                    title=entry.get("title"),
                    source_page=entry.get("index_page"),
                    notes="volume_index",
                )
        for key, row in vol_sheets.items():
            if not _index_covers(key, index_keys) and not _index_covers(
                key, master_keys_all
            ):
                _insert_finding(
                    conn,
                    kind="sheet_in_set_not_in_index",
                    sheet_number=row["sheet_number"],
                    drawing_volume_id=vol_id,
                    source_page=row["page"],
                    notes="volume_index",
                )

        _flag_duplicates(real_entries, vol_id, "volume_index")

    # Master vs per-discipline volume-index agreement. When the master and a
    # volume_index both exist, the volume_index defines the authoritative sheet
    # list for its discipline(s); divergences are flagged against the master so
    # an accurate sub-index doesn't suppress a stale master entry.
    if master_entries:
        master_vol_id = master_entries[0]["volume_id"]
        master_by_key = {
            normalize_sheet_number(e["sheet_number"]): e for e in master_entries
        }
        for (vol_id, source), entries in entries_by_volume_source.items():
            if source != "volume_index" or vol_id == master_vol_id:
                continue
            vol_sheets = sheets_by_volume.get(vol_id, {})
            vol_prefixes = _prefixes(
                row["sheet_number"] for row in vol_sheets.values()
            )
            if not vol_prefixes:
                continue
            project_set_keys = set(project_set.keys())
            # Restrict to volume_index entries that also exist as real sheets
            # somewhere in the project — kills schedule/legend code noise from
            # the sub-index parse.
            volume_index_keys = {
                normalize_sheet_number(e["sheet_number"])
                for e in entries
                if normalize_sheet_number(e["sheet_number"]) in project_set_keys
            }
            # Scope by EXACT sheet prefix, not startswith: distinct disciplines
            # can share a leading letter (Atlas Electrical `E`, Energy `EN`,
            # Building-envelope `EBM`), and a startswith test pulled EN*/EBM*
            # master entries into the Electrical volume's cross-check, flagging
            # them all as master_vs_volume_index disagreements (#39).
            master_in_scope = {
                key: entry
                for key, entry in master_by_key.items()
                if (mm := _SHEET_PREFIX_RE.match(entry["sheet_number"]))
                and mm.group(1).upper() in vol_prefixes
            }
            master_scope_keys = set(master_in_scope.keys())
            for key in volume_index_keys:
                if _index_covers(key, master_scope_keys):
                    continue
                if key in flagged_master_missing:
                    continue
                sample = next(
                    e for e in entries if normalize_sheet_number(e["sheet_number"]) == key
                )
                _insert_finding(
                    conn,
                    kind="sheet_in_set_not_in_index",
                    sheet_number=sample["sheet_number"],
                    drawing_volume_id=master_vol_id,
                    source_page=sample.get("index_page"),
                    notes="master_vs_volume_index",
                )
                flagged_master_missing.add(key)
            for key, entry in master_in_scope.items():
                if key in volume_index_keys or key in flagged_master_extra:
                    continue
                _insert_finding(
                    conn,
                    kind="sheet_in_index_not_in_set",
                    sheet_number=entry["sheet_number"],
                    drawing_volume_id=master_vol_id,
                    title=entry.get("title"),
                    source_page=entry.get("index_page"),
                    notes="master_vs_volume_index",
                )
                flagged_master_extra.add(key)

    config = None
    for pdf_path in volumes.values():
        config = load_drawing_config(Path(pdf_path).parent)
        break

    if config and config.title_block_calibrated:
        for vol_id, pdf_path in volumes.items():
            parsed = analyze_pdf(pdf_path, config=config)
            for mm in parsed.get("titleblock_mismatches", []):
                _insert_finding(
                    conn,
                    kind="sheet_number_mismatch",
                    sheet_number=mm["sheet_number"],
                    drawing_volume_id=vol_id,
                    title=mm.get("title"),
                    source_page=mm.get("page"),
                    notes="titleblock_crosscheck",
                )

    _emit_sheet_discipline_review_findings(conn)
    _emit_parse_anomaly_findings(conn)

    # Hold baseline verdicts on untrusted scopes at Evidence (ADR-0026 §6a):
    # a tripped invariant means parse-completeness on that prefix is suspect,
    # so the deterministic conclusion cannot be presented as a Candidate.
    untrusted = drawing_matrix.tripped_scopes(conn)
    if untrusted:
        from qc_core.drawing.matrix import _prefix_of

        reconciliation_kinds = (
            "sheet_in_index_not_in_set",
            "sheet_in_set_not_in_index",
            "duplicate_sheet_number",
        )
        placeholders = ",".join("?" * len(reconciliation_kinds))
        rows = conn.execute(
            f"SELECT id, sheet_number FROM findings WHERE kind IN ({placeholders})",
            reconciliation_kinds,
        ).fetchall()
        held = [
            r["id"] for r in rows if _prefix_of(r["sheet_number"] or "") in untrusted
        ]
        if held:
            id_marks = ",".join("?" * len(held))
            conn.execute(
                f"UPDATE findings SET status = 'evidence' WHERE id IN ({id_marks})",
                held,
            )


def index_project(
    project_folder: str | Path,
    *,
    force: bool = False,
) -> list[dict]:
    """Index all discovered drawing PDFs and compute project-level findings."""
    from qc_core.discovery import discover_drawing_pdfs, qc_sqlite_path

    root = Path(project_folder)
    db_path = qc_sqlite_path(root)
    config = load_drawing_config(root)
    conn = init_db(db_path)
    try:
        volumes = discover_drawing_pdfs(root)
        if not volumes:
            return []

        # Phase 1: collect project-wide bookmark prefixes so classify_index_scope
        # can filter outside-prefix junk (finish/hardware codes) from real
        # cross-volume references.
        from qc_core.drawing.parse import extract_bookmarks, _prefixes

        try:
            import fitz  # PyMuPDF
        except ImportError:  # pragma: no cover
            fitz = None  # type: ignore[assignment]

        project_prefixes: set[str] = set()
        project_sheet_keys: set[str] = set()
        if fitz is not None:
            for vol in volumes:
                try:
                    doc = fitz.open(vol.path)
                except Exception:
                    continue
                try:
                    bookmarks, _rate, _anoms = extract_bookmarks(doc)
                finally:
                    doc.close()
                project_prefixes |= _prefixes(s["sheet_number"] for s in bookmarks)
                project_sheet_keys |= {
                    normalize_sheet_number(s["sheet_number"]) for s in bookmarks
                }

        summaries: list[dict] = []
        any_reindexed = False
        for vol in volumes:
            summary = index_drawing_pdf(
                conn,
                vol.path,
                force=force,
                config=config,
                project_bookmark_prefixes=project_prefixes,
                project_sheet_keys=project_sheet_keys,
            )
            summaries.append(summary)
            if summary.get("indexed"):
                any_reindexed = True

        placeholders = ",".join("?" * len(DRAWING_FINDING_KINDS))
        has_findings = conn.execute(
            f"SELECT 1 FROM findings WHERE kind IN ({placeholders}) LIMIT 1",
            DRAWING_FINDING_KINDS,
        ).fetchone() is not None
        if any_reindexed or not has_findings:
            compute_drawing_findings(conn)
        conn.commit()
        return summaries
    finally:
        conn.close()


def needs_reindex(project_folder: str | Path) -> bool:
    """True if qc.sqlite missing or any drawing PDF newer than indexed mtime."""
    from qc_core.discovery import discover_drawing_pdfs, qc_sqlite_path

    root = Path(project_folder)
    db_path = qc_sqlite_path(root)
    if not db_path.is_file():
        return True

    conn = init_db(db_path)
    try:
        volumes = discover_drawing_pdfs(root)
        if not volumes:
            return False
        for vol in volumes:
            row = conn.execute(
                "SELECT pdf_mtime FROM drawing_volumes WHERE pdf_path = ?",
                (str(vol.path.resolve()),),
            ).fetchone()
            mtime = vol.path.stat().st_mtime
            if not row or abs(row["pdf_mtime"] - mtime) >= 0.001:
                return True
        return False
    finally:
        conn.close()
