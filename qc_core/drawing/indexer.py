"""Write drawing extraction results into qc.sqlite and populate findings (ADR-0014)."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from qc_core.db import init_db
from qc_core.drawing.kinds import DRAWING_FINDING_KINDS
from qc_core.drawing.config import load_drawing_config
from qc_core.drawing.discipline import infer_sheet_discipline
from qc_core.drawing.parse import (
    _prefixes,
    _SHEET_PREFIX_RE,
    analyze_pdf,
    normalize_sheet_number,
)


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


def _normalize_title_for_pairing(title: str | None) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().casefold())


# Some master-index title-lookahead parses glue a trailing issuance date onto
# the title text ("PARKING CONTROL EQUIPMENT 29 JUNE 2026" — NE A Street's
# "DD MONTH YYYY" format isn't caught by the numeric-date skip in
# _parse_index_lines). Strip it before comparing so a real title match isn't
# missed just because one side carries a bookmark's clean title and the other
# carries the index's date-glued title.
_TRAILING_DATE_RE = re.compile(
    r"\s+\d{1,2}\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"\s+\d{4}\s*$"
)


def _strip_trailing_date(title: str) -> str:
    return _TRAILING_DATE_RE.sub("", title).strip()


def _titles_match_for_pairing(a: str, b: str) -> bool:
    """Equal after stripping a trailing glued-on issuance date from either side."""
    if not a or not b:
        return False
    return _strip_trailing_date(a) == _strip_trailing_date(b)


# Titles that repeat across many unrelated sheets — an identical-title match
# against one of these is coincidence, not evidence the two keys are the same
# sheet (#85 guardrail: "skip titles like 'DETAILS' that repeat across sheets").
# This hardcoded set is a floor, not the whole guard — _pair_near_miss_variances
# ALSO requires the title be unique project-wide (see master_title_counts):
# Embassy Suites' "HARDSCAPE DETAILS" isn't in this list but genuinely repeats
# across a real series of distinct sheets (L300/L302/L304), and a title-only
# match against it wrongly paired three unrelated sheets during development.
_GENERIC_TITLES = {
    "details", "detail", "plan", "plans", "notes", "general notes",
    "schedule", "schedules", "elevations", "sections", "section",
    "cover sheet", "index", "legend",
}


def _pair_near_miss_variances(
    unmatched_index: list[dict],
    unmatched_set: list[dict],
    master_title_counts: dict[str, int],
) -> tuple[list[dict], set[str], set[str]]:
    """#85: pair an unmatched master-index key with an unmatched set key when
    they're plausibly the same physical sheet — identical non-generic title
    that is UNIQUE across the whole master index (not shared by any other
    listed sheet), or normalized sheet numbers within edit distance 1 (PK101
    index text vs PK-001 bookmark, an OCR/text-layer digit variance on the
    same sheet, #80).

    Returns (pairs, paired_index_keys, paired_set_keys). A pair is a dict with
    both sides' entry/row plus the reason ('title' or 'number'). Never pairs
    across different sheet-number prefixes unless the title match is exact —
    guards against pairing unrelated disciplines that happen to have a
    generic-adjacent title collision.
    """
    pairs: list[dict] = []
    paired_index_keys: set[str] = set()
    paired_set_keys: set[str] = set()

    set_by_key = {normalize_sheet_number(r["sheet_number"]): r for r in unmatched_set}
    used_set_keys: set[str] = set()

    def _prefix(sheet_number: str) -> str | None:
        m = _SHEET_PREFIX_RE.match(sheet_number)
        return m.group(1).upper() if m else None

    for entry in unmatched_index:
        idx_key = normalize_sheet_number(entry["sheet_number"])
        idx_title = _normalize_title_for_pairing(entry.get("title"))
        idx_prefix = _prefix(entry["sheet_number"])
        best: dict | None = None
        best_reason: str | None = None
        for set_key, row in set_by_key.items():
            if set_key in used_set_keys:
                continue
            set_title = _normalize_title_for_pairing(row.get("title"))
            set_prefix = _prefix(row["sheet_number"])
            same_prefix = idx_prefix is not None and idx_prefix == set_prefix
            stripped_idx_title = _strip_trailing_date(idx_title)
            # Generic (DETAILS, PLAN, ...) is never trusted, with or without
            # number corroboration — sequential detail sheets (A101/A102...)
            # are routinely each titled just "DETAILS" as a real series, not
            # duplicates of one sheet.
            titles_match = (
                _titles_match_for_pairing(idx_title, set_title)
                and stripped_idx_title not in _GENERIC_TITLES
                and len(stripped_idx_title) >= 6
            )
            title_match = (
                titles_match
                and master_title_counts.get(stripped_idx_title, 0) <= 1
            )
            if title_match:
                # Exact, project-wide-unique title match — trusted even
                # across differing prefixes.
                best, best_reason = row, "title"
                break
            # Edit distance 1 exactly (#85's spec) — _keys_near_miss allows up
            # to 2, calibrated for #80's different (admission) use case. Number
            # proximity ALONE is not reliable evidence: Embassy Suites has two
            # unrelated real sheets, L302 "HARDSCAPE DETAILS" (index) and
            # L-002 "SITE PLAN" (bookmark), whose normalized keys coincidentally
            # sit at edit distance 1. The one confirmed-real case (NE A Street
            # PK101/PK-001) has matching titles on BOTH sides (once the
            # index's date-glued title is stripped) — require that same
            # corroboration here too, not number proximity in isolation.
            if (
                same_prefix
                and titles_match
                and len(idx_key) == len(set_key)
                and sum(1 for x, y in zip(idx_key, set_key) if x != y) == 1
            ):
                best, best_reason = row, "number"
                break
        if best is not None:
            best_key = normalize_sheet_number(best["sheet_number"])
            used_set_keys.add(best_key)
            paired_index_keys.add(idx_key)
            paired_set_keys.add(best_key)
            pairs.append({"index_entry": entry, "set_row": best, "reason": best_reason})

    return pairs, paired_index_keys, paired_set_keys


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

    import json as _json

    meta = result["meta"]
    pattern = drawing_set_pattern(path)
    discipline = _discipline_from_filename(path)
    extraction_signal = _json.dumps(meta.get("extraction_signal") or {})

    # Preserve prior discipline-index confirmation decisions across reindex
    # (ADR-0024 Resolutions persist — an unchanged set never re-asks the
    # page-read question). Keyed by provenance for this volume.
    prior_layer_status: dict[str, tuple[str, str | None]] = {}
    if existing:
        for r in conn.execute(
            "SELECT provenance, confirmation_status, rationale "
            "FROM drawing_index_layers WHERE volume_id = ?",
            (existing["id"],),
        ).fetchall():
            prior_layer_status[r["provenance"]] = (
                r["confirmation_status"],
                r["rationale"],
            )

    if existing:
        volume_id = existing["id"]
        conn.execute("DELETE FROM drawing_sheets WHERE volume_id = ?", (volume_id,))
        conn.execute("DELETE FROM drawing_index_entries WHERE volume_id = ?", (volume_id,))
        conn.execute("DELETE FROM drawing_parse_anomalies WHERE volume_id = ?", (volume_id,))
        conn.execute("DELETE FROM drawing_index_duplicates WHERE volume_id = ?", (volume_id,))
        conn.execute("DELETE FROM drawing_index_layers WHERE volume_id = ?", (volume_id,))
        conn.execute(
            """
            UPDATE drawing_volumes
            SET pdf_mtime = ?, page_count = ?, discipline = ?, set_pattern = ?,
                extraction_signal = ?, indexed_at = datetime('now')
            WHERE id = ?
            """,
            (mtime, meta["total_pages"], discipline, pattern, extraction_signal, volume_id),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO drawing_volumes (
                pdf_path, pdf_mtime, page_count, discipline, set_pattern,
                extraction_signal
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(path), mtime, meta["total_pages"], discipline, pattern, extraction_signal),
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
                volume_id, sheet_number, title, page, confidence, discipline,
                building_prefix
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                volume_id,
                sheet["sheet_number"],
                sheet.get("title"),
                sheet["page"],
                sheet.get("confidence"),
                inf.discipline,
                sheet.get("building_prefix"),
            ),
        )

    for entry in result["index_entries"]:
        conn.execute(
            """
            INSERT INTO drawing_index_entries (
                volume_id, sheet_number, title, source, index_page, layer_provenance
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                volume_id,
                entry["sheet_number"],
                entry.get("title"),
                entry["source"],
                entry.get("index_page"),
                entry.get("layer_provenance"),
            ),
        )

    for layer in result.get("index_layers", []):
        prov = layer["provenance"]
        # A confirmed decision (admitted/rejected) on this provenance persists;
        # a still-candidate layer keeps rescanning as candidate.
        status = layer["confirmation_status"]
        rationale = None
        if prov in prior_layer_status and prior_layer_status[prov][0] != "candidate":
            status, rationale = prior_layer_status[prov]
        conn.execute(
            """
            INSERT INTO drawing_index_layers (
                volume_id, layer_kind, provenance, lead_sheet_number,
                index_page, discipline_prefix, confirmation_status, signals, rationale
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                volume_id,
                layer["layer_kind"],
                prov,
                layer.get("lead_sheet_number"),
                layer.get("index_page"),
                layer.get("discipline_prefix"),
                status,
                _json.dumps(layer.get("signals") or {}),
                rationale,
            ),
        )

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

    for dup in result.get("index_duplicates", []):
        conn.execute(
            "INSERT INTO drawing_index_duplicates "
            "(volume_id, sheet_number, title, count, page, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                volume_id,
                dup["sheet_number"],
                dup.get("title"),
                dup["count"],
                dup.get("page"),
                dup.get("source"),
            ),
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
    if kind in ("sheet_discipline_reviewer_resolution", "discipline_index_missing"):
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


def _emit_index_duplicate_findings(conn: sqlite3.Connection) -> None:
    """Insert duplicate_sheet_number findings from drawing_index_duplicates (#76).

    A sheet number listed twice within the SAME index table (e.g. Artisan
    Prescot's civil index bare `NCG01` x2) is the index-channel counterpart
    to the existing bookmark-side duplicate detection (_flag_duplicates) —
    that one only ever caught bookmark-channel collisions; this is the
    remaining undetected half. notes uses the same "{source} x{count}"
    convention as the existing bookmark/master/volume-index duplicate
    findings for consistency.
    """
    rows = conn.execute(
        "SELECT volume_id, sheet_number, title, count, page, source "
        "FROM drawing_index_duplicates ORDER BY volume_id, sheet_number"
    ).fetchall()
    for row in rows:
        _insert_finding(
            conn,
            kind="duplicate_sheet_number",
            sheet_number=row["sheet_number"],
            drawing_volume_id=row["volume_id"],
            title=row["title"],
            source_page=row["page"],
            notes=f"{row['source'] or 'index'} x{row['count']}",
        )


def _emit_discipline_index_missing_findings(conn: sqlite3.Connection) -> None:
    """Emit one discipline_index_missing finding per prefix that has sheets in the set
    but no accepted index region covering it (issue #71).

    This is the emit-eligible promotion of the prefix_absent_from_index invariant.
    Only fires when the volume has at least one other indexed prefix (i.e. there ARE
    discipline indexes in the set — their absence for this prefix is meaningful, not
    just a no-index-anywhere volume).
    """
    from qc_core.drawing.parse import _SHEET_PREFIX_RE

    # Determine which prefixes are covered by any index entry in the project
    indexed_prefixes: set[str] = set()
    for row in conn.execute("SELECT sheet_number FROM drawing_index_entries").fetchall():
        m = _SHEET_PREFIX_RE.match(row["sheet_number"] or "")
        if m:
            indexed_prefixes.add(m.group(1).upper())

    if not indexed_prefixes:
        return

    # Build per-volume, per-prefix sheet counts from drawing_sheets
    vol_prefix_sheet_count: dict[tuple[int, str], int] = {}
    for row in conn.execute(
        "SELECT volume_id, sheet_number FROM drawing_sheets"
    ).fetchall():
        m = _SHEET_PREFIX_RE.match(row["sheet_number"] or "")
        if not m:
            continue
        prefix = m.group(1).upper()
        key = (row["volume_id"], prefix)
        vol_prefix_sheet_count[key] = vol_prefix_sheet_count.get(key, 0) + 1

    # Build per-volume, per-prefix index coverage
    vol_prefix_indexed: set[tuple[int, str]] = set()
    for row in conn.execute(
        "SELECT volume_id, sheet_number FROM drawing_index_entries"
    ).fetchall():
        m = _SHEET_PREFIX_RE.match(row["sheet_number"] or "")
        if m:
            vol_prefix_indexed.add((row["volume_id"], m.group(1).upper()))

    # Per volume: prefixes with sheets but no index rows, for volumes that have
    # at least one indexed prefix
    MIN_SHEETS = 3

    vol_has_any_index = {
        row["volume_id"]
        for row in conn.execute("SELECT DISTINCT volume_id FROM drawing_index_entries").fetchall()
    }

    for (vol_id, prefix), count in vol_prefix_sheet_count.items():
        if count < MIN_SHEETS:
            continue
        if vol_id not in vol_has_any_index:
            continue
        if (vol_id, prefix) in vol_prefix_indexed:
            continue
        _insert_finding(
            conn,
            kind="discipline_index_missing",
            sheet_number=f"{prefix}*",
            drawing_volume_id=vol_id,
            notes=f"prefix={prefix} sheets_in_set={count}",
            expected_action="emit_markup",
        )


def _building_set(conn: sqlite3.Connection) -> bool:
    """True when this project uses the #88 per-layer index-channel model."""
    return (
        conn.execute("SELECT 1 FROM drawing_index_layers LIMIT 1").fetchone()
        is not None
    )


def _reconcile_layers(
    conn: sqlite3.Connection,
    sheets_by_volume: dict[int, dict[str, dict]],
) -> None:
    """Per-layer reconciliation for building-namespaced sets (ADR-0026 / #88).

    Each admitted/candidate index layer is reconciled INDEPENDENTLY against its
    own volume's bookmarks — no cross-layer union, so a master that omits a
    sheet its discipline index carries surfaces as UNLISTED-against-master
    (the reason #88 exists). Rejected layers are skipped entirely (expunged).

    Findings from a still-`candidate` discipline layer are held at
    status='evidence' behind a tripped `discipline_index_unconfirmed` invariant
    (scoped to the layer provenance): a false channel poisons nothing until a
    Claude page read admits it. A key is never flagged UNLISTED against a layer
    for a discipline that layer does not carry at all (so a master that omits an
    entire discipline — Valrico Technology — does not flood).
    """
    from qc_core.drawing.matrix import CHECK_NAME
    from qc_core.drawing.parse import _SHEET_PREFIX_RE

    def _disc(sn: str) -> str | None:
        m = _SHEET_PREFIX_RE.match(sn or "")
        return m.group(1).upper() if m else None

    layers = conn.execute(
        "SELECT id, volume_id, layer_kind, provenance, confirmation_status "
        "FROM drawing_index_layers ORDER BY volume_id, provenance"
    ).fetchall()

    entries_by_layer: dict[tuple[int, str], list[dict]] = {}
    for row in conn.execute(
        "SELECT volume_id, sheet_number, title, index_page, layer_provenance "
        "FROM drawing_index_entries WHERE layer_provenance IS NOT NULL"
    ).fetchall():
        entries_by_layer.setdefault(
            (row["volume_id"], row["layer_provenance"]), []
        ).append(dict(row))

    # The unconfirmed-layer gate is recomputed every run from the layers'
    # confirmation_status (the durable decision lives in drawing_index_layers,
    # not the invariant). Clear stale tripped rows; re-trip only still-candidate
    # layers below.
    conn.execute(
        "DELETE FROM invariant_results WHERE check_name = ? "
        "AND invariant = 'discipline_index_unconfirmed'",
        (CHECK_NAME,),
    )

    candidate_provenances: list[str] = []

    for layer in layers:
        if layer["confirmation_status"] == "rejected":
            continue
        vol_id = layer["volume_id"]
        prov = layer["provenance"]
        entries = entries_by_layer.get((vol_id, prov), [])
        if not entries:
            continue
        if layer["confirmation_status"] == "candidate":
            candidate_provenances.append(prov)

        vol_sheets = sheets_by_volume.get(vol_id, {})
        vol_keys = set(vol_sheets.keys())
        layer_keys = {normalize_sheet_number(e["sheet_number"]): e for e in entries}
        covered_disc = {_disc(e["sheet_number"]) for e in entries}
        covered_disc.discard(None)

        # CNL: listed in this layer, absent from this volume's bound sheets.
        for key, e in layer_keys.items():
            if not _index_covers(key, vol_keys):
                _insert_finding(
                    conn,
                    kind="sheet_in_index_not_in_set",
                    sheet_number=e["sheet_number"],
                    drawing_volume_id=vol_id,
                    title=e.get("title"),
                    source_page=e.get("index_page"),
                    notes=prov,
                )
        # UNLISTED: bound sheet of a discipline this layer carries, but absent
        # from the layer. Disciplines the layer omits entirely are out of scope.
        for key, row in vol_sheets.items():
            if _disc(row["sheet_number"]) not in covered_disc:
                continue
            if not _index_covers(key, set(layer_keys.keys())):
                _insert_finding(
                    conn,
                    kind="sheet_in_set_not_in_index",
                    sheet_number=row["sheet_number"],
                    drawing_volume_id=vol_id,
                    source_page=row["page"],
                    notes=prov,
                )
        _flag_duplicates_layer(conn, entries, vol_id, prov)

    # Hold candidate-layer findings at Evidence + trip the unconfirmed invariant.
    for prov in candidate_provenances:
        held = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM findings WHERE notes = ? AND kind IN "
                "('sheet_in_index_not_in_set', 'sheet_in_set_not_in_index', "
                "'duplicate_sheet_number')",
                (prov,),
            ).fetchall()
        ]
        if held:
            marks = ",".join("?" * len(held))
            conn.execute(
                f"UPDATE findings SET status = 'evidence' WHERE id IN ({marks})",
                held,
            )
        detail = {
            "provenance": prov,
            "held_findings": len(held),
            "note": (
                "Deterministic discipline-index candidate. MANDATORY page read: "
                "open the lead sheet, confirm this is a real Discipline Index, "
                "then admit/reject via --apply-judgments channels[] before its "
                "findings can emit (ADR-0026)."
            ),
        }
        import json as _json

        conn.execute(
            "INSERT OR REPLACE INTO invariant_results "
            "(check_name, invariant, scope, status, detail) "
            "VALUES (?, 'discipline_index_unconfirmed', ?, 'tripped', ?)",
            (CHECK_NAME, prov, _json.dumps(detail)),
        )


def _flag_duplicates_layer(
    conn: sqlite3.Connection, entries: list[dict], vol_id: int, prov: str
) -> None:
    counts: dict[str, int] = {}
    by_key: dict[str, dict] = {}
    for e in entries:
        key = normalize_sheet_number(e["sheet_number"])
        counts[key] = counts.get(key, 0) + 1
        by_key.setdefault(key, e)
    for key, count in counts.items():
        if count > 1:
            e = by_key[key]
            _insert_finding(
                conn,
                kind="duplicate_sheet_number",
                sheet_number=e["sheet_number"],
                drawing_volume_id=vol_id,
                source_page=e.get("index_page"),
                notes=f"{prov} x{count}",
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

    # #84: a Reviewer's dismiss/reclassify judgment on a candidate finding is
    # a durable Resolution (ADR-0024), not scoped to one evidence snapshot —
    # preserve it across the delete-then-reinsert recompute cycle below so a
    # plain reindex doesn't resurrect a finding the Reviewer already refuted.
    prior_judgments = {
        (r["evidence_key"], r["kind"]): (r["status"], r["judgment_rationale"])
        for r in conn.execute(
            f"SELECT evidence_key, kind, status, judgment_rationale FROM findings "
            f"WHERE kind IN ({','.join('?' * len(DRAWING_FINDING_KINDS))}) "
            f"AND status = 'dismissed' AND evidence_key IS NOT NULL",
            DRAWING_FINDING_KINDS,
        ).fetchall()
    }

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
        # Index presence corroborates regardless of its own count: listed once,
        # two physical pages claim one indexed number (Elk Grove 'E. 304');
        # listed twice, BOTH channels duplicate the key (Artisan 'NCG01' — the
        # index repeats the row too). Only index-absent collisions are channel
        # noise (Quarry Oaks MEP 'E1' x38).
        corroborated = (
            _index_key_counts.get(_norm_key, 0) >= 1
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
        elif count > 1:
            # Same-key collision without corroboration (#74): never collapse
            # silently. Quarantine as a parse_anomaly at status='evidence' so
            # the collision must be judged, not suppressed (ADR-0027). N rows
            # collapsing to one key is the suppressed class: "bookmark parse
            # 100%" must account by row, and downstream key-level dedup must
            # leave a signal behind.
            first = _bookmark_first[(vol_id, _norm_key)]
            titles = sorted(t for t in _bookmark_titles[(vol_id, _norm_key)] if t)
            raw_text = (
                f"{count} bookmarks collapse to key {_norm_key} "
                f"(first '{first['sheet_number']}' p.{first['page']}; "
                f"titles: {'; '.join(titles[:6]) if titles else 'none'})"
            )
            conn.execute(
                """
                INSERT INTO findings (
                    drawing_volume_id, kind, expected_action, severity,
                    sheet_number, source_page, notes, context, status, evidence_key
                ) VALUES (?, 'parse_anomaly', 'info_only', 'low', ?, ?, ?,
                          'channel=bookmarks', 'evidence', ?)
                """,
                (
                    vol_id,
                    first["sheet_number"],
                    first["page"],
                    raw_text,
                    f"parse_anomaly:{vol_id}:bookmark_collision:{_norm_key}",
                ),
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
                    "title": row.get("title"),
                },
            )
    project_prefixes = _prefixes(row["sheet_number"] for row in project_set.values())

    # #88: building-namespaced sets use the per-layer channel reconciliation
    # (each index layer its own channel); the flat master/volume legacy blocks
    # below are skipped for them so their outcomes are provably unchanged on
    # non-namespaced fixtures (Embassy/Atlas/QO/Juvenile/Kadlec).
    building = _building_set(conn)
    if building:
        _reconcile_layers(conn, sheets_by_volume)

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
    if master_entries and not building:
        master_vol_id = master_entries[0]["volume_id"]
        master_keys = {normalize_sheet_number(e["sheet_number"]) for e in master_entries}
        set_keys = set(project_set.keys())

        unmatched_index_entries = [
            e for e in master_entries
            if normalize_sheet_number(e["sheet_number"]) not in set_keys
        ]
        unmatched_set_rows = [
            row for key, row in project_set.items()
            if not _index_covers(key, master_keys)
        ]
        master_title_counts: dict[str, int] = {}
        for e in master_entries:
            t = _strip_trailing_date(_normalize_title_for_pairing(e.get("title")))
            if t:
                master_title_counts[t] = master_title_counts.get(t, 0) + 1

        # #85: pair plausible same-sheet variances (PK101 index text vs PK-001
        # bookmark) into one sheet_number_mismatch (AVW) BEFORE the ordinary
        # one-sided CNL/UNLISTED findings below — a paired key is a real
        # variance, not two independent defects. Only keys unmatched by BOTH
        # exact and area-suffix matching are eligible (#85 guardrail).
        pairs, paired_index_keys, paired_set_keys = _pair_near_miss_variances(
            unmatched_index_entries, unmatched_set_rows, master_title_counts
        )
        for pair in pairs:
            entry, row = pair["index_entry"], pair["set_row"]
            _insert_finding(
                conn,
                kind="sheet_number_mismatch",
                sheet_number=entry["sheet_number"],
                drawing_volume_id=entry["volume_id"],
                title=entry.get("title") or row.get("title"),
                source_page=entry.get("index_page"),
                notes=f"index_vs_set_variance:set={row['sheet_number']}",
            )
            flagged_master_extra.add(normalize_sheet_number(entry["sheet_number"]))
            flagged_master_missing.add(normalize_sheet_number(row["sheet_number"]))

        for entry in unmatched_index_entries:
            key = normalize_sheet_number(entry["sheet_number"])
            if key in paired_index_keys:
                continue
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
        for row in unmatched_set_rows:
            key = normalize_sheet_number(row["sheet_number"])
            if key in paired_set_keys:
                continue
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
        if source != "volume_index" or building:
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
    if master_entries and not building:
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
            vol_bookmark_keys = set(vol_sheets.keys())
            for key, entry in master_in_scope.items():
                if key in volume_index_keys or key in flagged_master_extra:
                    continue
                # #79: "not in set" must mean absent from the SET (bookmarks),
                # not merely absent from this volume's own sub-index. A missing
                # or false-positive volume index (elevator spec / symbol legend
                # mis-detected as an index page, #83) otherwise flags every
                # legitimately-bookmarked sheet in the discipline as a false
                # positive. Genuine absence from the set is already covered by
                # the master-vs-whole-project-set check above; a stale/absent
                # sub-index alone surfaces via discipline_index_missing instead.
                if key in vol_bookmark_keys:
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
    _emit_index_duplicate_findings(conn)
    _emit_discipline_index_missing_findings(conn)

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

    # #81: a not-in-set/not-in-index finding whose key is actually reconciled
    # in the matrix is self-contradictory regardless of which upstream bug
    # produced it — hold at evidence until judgment examines it.
    drawing_matrix.evaluate_finding_contradictions(conn)

    # #84: re-apply preserved dismiss judgments last, after every other status
    # write above (candidate default, evidence-holds, invariant contradiction
    # holds) — a Reviewer's dismissal always wins over a freshly recomputed
    # verdict for the same (evidence_key, kind).
    if prior_judgments:
        for (evidence_key, kind), (status, rationale) in prior_judgments.items():
            conn.execute(
                "UPDATE findings SET status = ?, judgment_rationale = ? "
                "WHERE evidence_key = ? AND kind = ?",
                (status, rationale, evidence_key, kind),
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
