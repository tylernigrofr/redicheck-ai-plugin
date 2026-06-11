"""Reconciliation matrix + fail-loud invariants for the drawing-index check (ADR-0026).

The matrix is the Evidence artifact: one row per (entity-key, channel, volume)
recording present/absent with provenance, computed deterministically and
persisted without a verdict. Invariants are deterministic queries over the
matrix that catch silent parse failures (the #53 ISO-date drop class); a
tripped invariant marks its scope untrusted until a judgment node resolves it
or the Reviewer overrides it (ADR-0024).
"""

from __future__ import annotations

import json
import sqlite3

from qc_core.drawing.parse import _SHEET_PREFIX_RE, _prefixes, normalize_sheet_number

CHECK_NAME = "drawing-index"

# Channels for the drawing-index instantiation of the matrix (ADR-0026 §5).
CHANNEL_BOOKMARKS = "bookmarks"
CHANNEL_MASTER = "master_index"
CHANNEL_VOLUME = "volume_index"

# An invariant trips only past these floors so single-sheet oddities don't
# mark whole projects untrusted; below the floor the disagreement still
# surfaces as an ordinary Evidence/finding row.
PREFIX_MIN_SHEETS = 3
PREFIX_MIN_ENTRIES = 3


def _prefix_of(sheet_number: str) -> str | None:
    m = _SHEET_PREFIX_RE.match(sheet_number or "")
    return m.group(1).upper() if m else None


def build_matrix(conn: sqlite3.Connection) -> int:
    """Rebuild the drawing-index reconciliation matrix from indexed data.

    Returns the number of matrix rows written.
    """
    conn.execute(
        "DELETE FROM reconciliation_matrix WHERE check_name = ?", (CHECK_NAME,)
    )

    rows_written = 0

    def _write(entity_key, channel, volume_id, raw_value, page, detail=None):
        nonlocal rows_written
        conn.execute(
            """
            INSERT OR IGNORE INTO reconciliation_matrix (
                check_name, entity_key, channel, volume_id,
                present, raw_value, page, detail
            ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                CHECK_NAME,
                entity_key,
                channel,
                volume_id,
                raw_value,
                page,
                json.dumps(detail) if detail else None,
            ),
        )
        rows_written += 1

    for row in conn.execute(
        "SELECT volume_id, sheet_number, title, page FROM drawing_sheets"
    ).fetchall():
        _write(
            normalize_sheet_number(row["sheet_number"]),
            CHANNEL_BOOKMARKS,
            row["volume_id"],
            row["sheet_number"],
            row["page"],
            {"title": row["title"]} if row["title"] else None,
        )

    for row in conn.execute(
        "SELECT volume_id, sheet_number, title, source, index_page FROM drawing_index_entries"
    ).fetchall():
        channel = CHANNEL_MASTER if row["source"] == "master_index" else CHANNEL_VOLUME
        _write(
            normalize_sheet_number(row["sheet_number"]),
            channel,
            row["volume_id"],
            row["sheet_number"],
            row["index_page"],
            {"title": row["title"]} if row["title"] else None,
        )

    return rows_written


def evaluate_invariants(conn: sqlite3.Connection) -> list[dict]:
    """Evaluate the universal-core invariants over the persisted matrix.

    Existing 'resolved'/'overridden' rows are preserved across re-evaluation
    (a Resolution persists, ADR-0024); 'tripped' rows are recomputed. Returns
    all invariant rows for the check, freshly evaluated.
    """
    conn.execute(
        "DELETE FROM invariant_results WHERE check_name = ? AND status = 'tripped'",
        (CHECK_NAME,),
    )
    kept = {
        (r["invariant"], r["scope"])
        for r in conn.execute(
            "SELECT invariant, scope FROM invariant_results WHERE check_name = ?",
            (CHECK_NAME,),
        ).fetchall()
    }

    matrix = conn.execute(
        "SELECT entity_key, channel, raw_value FROM reconciliation_matrix "
        "WHERE check_name = ?",
        (CHECK_NAME,),
    ).fetchall()

    by_prefix_channel: dict[str, dict[str, set[str]]] = {}
    for row in matrix:
        prefix = _prefix_of(row["raw_value"]) or _prefix_of(row["entity_key"])
        if not prefix:
            continue
        chans = by_prefix_channel.setdefault(prefix, {})
        chans.setdefault(row["channel"], set()).add(row["entity_key"])

    has_any_index = any(
        r["channel"] in (CHANNEL_MASTER, CHANNEL_VOLUME) for r in matrix
    )

    tripped: list[dict] = []

    def _trip(invariant: str, scope: str, detail: dict) -> None:
        if (invariant, scope) in kept:
            return  # already resolved/overridden; the Resolution persists
        conn.execute(
            """
            INSERT OR REPLACE INTO invariant_results (
                check_name, invariant, scope, status, detail
            ) VALUES (?, ?, ?, 'tripped', ?)
            """,
            (CHECK_NAME, invariant, scope, json.dumps(detail)),
        )
        tripped.append({"invariant": invariant, "scope": scope, "detail": detail})

    for prefix, chans in sorted(by_prefix_channel.items()):
        sheet_keys = chans.get(CHANNEL_BOOKMARKS, set())
        index_keys = chans.get(CHANNEL_MASTER, set()) | chans.get(CHANNEL_VOLUME, set())

        # prefix_absent_from_index: a discipline group physically present in
        # the set with zero index coverage. The #53 silent-drop class: the
        # Citadel Structural index used ISO dates, the parser dropped every
        # row, and the only signal was a print line. Only meaningful when the
        # project has an index at all.
        if (
            has_any_index
            and len(sheet_keys) >= PREFIX_MIN_SHEETS
            and not index_keys
        ):
            _trip(
                "prefix_absent_from_index",
                prefix,
                {
                    "sheets_in_set": len(sheet_keys),
                    "sample": sorted(sheet_keys)[:5],
                },
            )

        # prefix_absent_from_set: an indexed group with zero physical sheets.
        # Either index parse noise that survived filtering, or a sub-project /
        # missing-volume situation (#54's '- Shed' shape). Judgment required.
        if len(index_keys) >= PREFIX_MIN_ENTRIES and not sheet_keys:
            _trip(
                "prefix_absent_from_set",
                prefix,
                {
                    "entries_in_index": len(index_keys),
                    "sample": sorted(index_keys)[:5],
                },
            )

        # prefix_unreconciled: prefix has rows in BOTH bookmark and index
        # channels but ZERO entity keys reconcile (no key present in both).
        # Catches channel-wide key corruption that prefix_absent_* structurally
        # misses — Elk Grove E had 30 index rows + 32 bookmarks, zero matches
        # after the prefix-space truncation bug (#64). Requires >=2 on each
        # side to avoid tripping on prefixes where a 1-entry channel is simply
        # noise (those are covered by prefix_absent_* already).
        if (
            has_any_index
            and len(sheet_keys) >= 2
            and len(index_keys) >= 2
        ):
            reconciled_keys = sheet_keys & index_keys
            if not reconciled_keys:
                _trip(
                    "prefix_unreconciled",
                    prefix,
                    {
                        "bookmark_count": len(sheet_keys),
                        "index_count": len(index_keys),
                        "sample_bookmarks": sorted(sheet_keys)[:5],
                        "sample_index": sorted(index_keys)[:5],
                    },
                )

    # completeness_sweep: synthetic invariant — always trips on every
    # evaluate_invariants() call (representing the mandatory holistic sweep
    # before emit, ADR-0027 §4). Resolved only via --apply-judgments with a
    # rationale summarizing what was scanned. Re-trips whenever invariants are
    # recomputed on a changed set.
    _trip(
        "completeness_sweep",
        "__project__",
        {
            "note": (
                "Mandatory completeness sweep before emit (ADR-0027). "
                "Run --mode=sweep, scan suspicious prefixes for suppressed-class "
                "issues, record resolution via --apply-judgments."
            )
        },
    )

    return all_invariants(conn)


def compute_scoreboard(conn: sqlite3.Connection) -> list[dict]:
    """Per-prefix scoreboard from reconciliation_matrix + parse_anomaly findings.

    Returns a list of dicts (one per prefix, plus one '??' row for anomalies
    with no attributable prefix), sorted by prefix.  Each row:
        prefix, index_count, bookmark_count, reconciled, disputed, anomalies,
        zero_reconciled (bool flag for display).

    Included in --mode=preview output and --mode=matrix JSON as 'scoreboard'
    (ADR-0026 / issue #67 Part 2).
    """
    matrix_rows = conn.execute(
        "SELECT entity_key, channel, raw_value FROM reconciliation_matrix "
        "WHERE check_name = ?",
        (CHECK_NAME,),
    ).fetchall()

    # Build per-prefix channel→key sets
    by_prefix: dict[str, dict[str, set[str]]] = {}
    for row in matrix_rows:
        prefix = _prefix_of(row["raw_value"]) or _prefix_of(row["entity_key"])
        if not prefix:
            prefix = "??"
        chans = by_prefix.setdefault(prefix, {})
        chans.setdefault(row["channel"], set()).add(row["entity_key"])

    # Determine which channels actually exist for the project
    all_channels = {r["channel"] for r in matrix_rows}
    has_index_channel = bool(all_channels & {CHANNEL_MASTER, CHANNEL_VOLUME})

    # Per-prefix anomaly counts (parse_anomaly findings, ADR-0027 / #65)
    anomaly_rows = conn.execute(
        "SELECT sheet_number FROM findings WHERE kind = 'parse_anomaly'"
    ).fetchall()
    anomaly_by_prefix: dict[str, int] = {}
    for arow in anomaly_rows:
        sn = arow["sheet_number"] or ""
        pfx = _prefix_of(sn) if sn else None
        key = pfx if pfx else "??"
        anomaly_by_prefix[key] = anomaly_by_prefix.get(key, 0) + 1

    # Collect all prefixes from matrix and anomalies
    all_prefixes = set(by_prefix.keys()) | set(anomaly_by_prefix.keys())

    scoreboard = []
    for prefix in sorted(all_prefixes):
        chans = by_prefix.get(prefix, {})
        bookmark_keys = chans.get(CHANNEL_BOOKMARKS, set())
        index_keys = chans.get(CHANNEL_MASTER, set()) | chans.get(CHANNEL_VOLUME, set())
        reconciled_keys = bookmark_keys & index_keys
        disputed_keys = bookmark_keys.symmetric_difference(index_keys)
        reconciled = len(reconciled_keys)
        disputed = len(disputed_keys)
        index_count = len(index_keys)
        bookmark_count = len(bookmark_keys)
        anomalies = anomaly_by_prefix.get(prefix, 0)
        zero_reconciled = has_index_channel and bookmark_count > 0 and index_count > 0 and reconciled == 0
        scoreboard.append(
            {
                "prefix": prefix,
                "index_count": index_count,
                "bookmark_count": bookmark_count,
                "reconciled": reconciled,
                "disputed": disputed,
                "anomalies": anomalies,
                "zero_reconciled": zero_reconciled,
            }
        )
    return scoreboard


def sweep_worklist(conn: sqlite3.Connection) -> list[dict]:
    """Compute the sweep worklist for --mode=sweep.

    Returns scoreboard for ALL prefixes plus full side-by-side raw dumps ONLY
    for suspicious prefixes (any parse anomalies, any disputed rows,
    reconciled==0, or index_count != bookmark_count).  Clean prefixes are
    included as scoreboard-only rows (no dump).

    Each entry:
        prefix, index_count, bookmark_count, reconciled, disputed, anomalies,
        zero_reconciled, suspicious (bool), index_rows (list|None), bookmark_rows (list|None).
    """
    scoreboard = compute_scoreboard(conn)

    # Build raw side-by-side dumps for suspicious prefixes
    matrix_rows = conn.execute(
        "SELECT entity_key, channel, raw_value, page FROM reconciliation_matrix "
        "WHERE check_name = ? ORDER BY page, entity_key",
        (CHECK_NAME,),
    ).fetchall()

    from qc_core.drawing.parse import normalize_sheet_number

    index_by_prefix: dict[str, list[dict]] = {}
    bookmark_by_prefix: dict[str, list[dict]] = {}
    for row in matrix_rows:
        prefix = _prefix_of(row["raw_value"]) or _prefix_of(row["entity_key"]) or "??"
        entry = {
            "raw": row["raw_value"],
            "key": row["entity_key"],
            "page": row["page"],
        }
        if row["channel"] in (CHANNEL_MASTER, CHANNEL_VOLUME):
            index_by_prefix.setdefault(prefix, []).append(entry)
        elif row["channel"] == CHANNEL_BOOKMARKS:
            bookmark_by_prefix.setdefault(prefix, []).append(entry)

    anomaly_rows = conn.execute(
        "SELECT sheet_number, notes FROM findings WHERE kind = 'parse_anomaly' ORDER BY sheet_number"
    ).fetchall()
    anomaly_by_prefix: dict[str, list[dict]] = {}
    for arow in anomaly_rows:
        sn = arow["sheet_number"] or ""
        pfx = _prefix_of(sn) if sn else None
        key = pfx if pfx else "??"
        anomaly_by_prefix.setdefault(key, []).append({"sheet_number": sn, "notes": arow["notes"]})

    result = []
    for row in scoreboard:
        prefix = row["prefix"]
        suspicious = (
            row["anomalies"] > 0
            or row["disputed"] > 0
            or row["zero_reconciled"]
            or row["index_count"] != row["bookmark_count"]
        )
        entry = dict(row)
        entry["suspicious"] = suspicious
        if suspicious:
            entry["index_rows"] = index_by_prefix.get(prefix, [])
            entry["bookmark_rows"] = bookmark_by_prefix.get(prefix, [])
            entry["anomaly_rows"] = anomaly_by_prefix.get(prefix, [])
        else:
            entry["index_rows"] = None
            entry["bookmark_rows"] = None
            entry["anomaly_rows"] = None
        result.append(entry)
    return result


def all_invariants(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM invariant_results WHERE check_name = ? ORDER BY invariant, scope",
        (CHECK_NAME,),
    ).fetchall()
    return [dict(r) for r in rows]


def tripped_scopes(conn: sqlite3.Connection) -> set[str]:
    """Prefixes whose invariants are tripped and unresolved."""
    rows = conn.execute(
        "SELECT scope FROM invariant_results "
        "WHERE check_name = ? AND status = 'tripped'",
        (CHECK_NAME,),
    ).fetchall()
    return {r["scope"] for r in rows if r["scope"]}


def _normalize_raw(text: str) -> str:
    """Strip, casefold, collapse internal whitespace for forgiving comparison."""
    import re
    return re.sub(r"\s+", " ", text.strip().casefold())


def _raw_text_for_finding(conn: sqlite3.Connection, evidence_key: str) -> str | None:
    """Return the stored raw source text for a finding row (ADR-0027 confirm-by-copying).

    For parse_anomaly findings the raw text lives in ``notes``.
    For reconciliation-based findings the raw text is the ``raw_value`` stored in
    ``reconciliation_matrix`` for that evidence_key.  Returns None when no row is found.
    """
    row = conn.execute(
        "SELECT kind, notes FROM findings WHERE evidence_key = ? AND status = 'evidence' LIMIT 1",
        (evidence_key,),
    ).fetchone()
    if row is None:
        return None
    if row["kind"] == "parse_anomaly":
        return row["notes"] or ""
    # Reconciliation-based: look up raw_value from the matrix.  The entity_key
    # stored in findings matches entity_key in reconciliation_matrix.
    mat_row = conn.execute(
        "SELECT raw_value FROM reconciliation_matrix WHERE check_name = ? AND entity_key = ? LIMIT 1",
        (CHECK_NAME, evidence_key),
    ).fetchone()
    return mat_row["raw_value"] if mat_row else None


def apply_judgments(conn: sqlite3.Connection, payload: dict) -> dict:
    """Apply a judgment node's schema-constrained decisions (ADR-0026 §3-4).

    Payload shape:
        {
          "decisions": [
            {"evidence_key": str, "action": "promote"|"dismiss"|"reclassify",
             "kind": str (required for reclassify), "rationale": str,
             "raw_text": str (required for dismiss — ADR-0027 confirm-by-copying)}
          ],
          "invariants": [
            {"id": int, "status": "resolved"|"overridden", "rationale": str}
          ]
        }

    Dismiss decisions must include a ``raw_text`` field whose value string-matches
    the stored raw source text of that evidence row (after strip+casefold+whitespace
    collapse).  Missing or mismatched raw_text causes the entire file to be rejected
    with an error listing each offending decision — nothing is written (atomic).

    Promote and reclassify decisions do not require raw_text.

    A shared rationale string appearing on more than 3 decisions in the file
    triggers a warning (printed to stdout) but does not reject.

    Returns counts of applied changes.
    """
    import sys
    from collections import Counter

    from qc_core.drawing.kinds import DRAWING_FINDING_KINDS

    decisions = payload.get("decisions", [])

    # --- shared-rationale warning (before any writes) ---
    rationale_counts: Counter = Counter()
    for dec in decisions:
        r = dec.get("rationale", "").strip()
        if r:
            rationale_counts[r] += 1
    for rationale, count in rationale_counts.items():
        if count > 3:
            print(
                f"WARNING: shared rationale across {count} rows — rationales must "
                f"describe the row, not the defect (ADR-0027): \"{rationale}\"",
                file=sys.stderr,
            )

    # --- strict raw_text validation for dismissals (all-or-nothing) ---
    errors: list[str] = []
    for dec in decisions:
        if dec.get("action") != "dismiss":
            continue
        key = dec["evidence_key"]
        provided = dec.get("raw_text")
        if not provided:
            expected = _raw_text_for_finding(conn, key)
            hint = f' (expected: "{expected}")' if expected is not None else " (finding not found)"
            errors.append(f"  dismiss {key!r}: raw_text missing{hint}")
            continue
        expected = _raw_text_for_finding(conn, key)
        if expected is None:
            # Finding not found — still validate as an error so the file is rejected
            errors.append(f"  dismiss {key!r}: finding not found in evidence")
            continue
        if _normalize_raw(provided) != _normalize_raw(expected):
            errors.append(
                f"  dismiss {key!r}: raw_text mismatch\n"
                f"    provided: \"{provided}\"\n"
                f"    expected: \"{expected}\""
            )
    if errors:
        raise ValueError(
            "Decisions file rejected — raw_text confirm-by-copying failed (ADR-0027).\n"
            "No changes were applied. Fix the following dismissals:\n"
            + "\n".join(errors)
        )

    applied = {"promoted": 0, "dismissed": 0, "reclassified": 0, "invariants": 0}
    kind_marks = ",".join("?" * len(DRAWING_FINDING_KINDS))

    for dec in decisions:
        key = dec["evidence_key"]
        action = dec["action"]
        rationale = dec.get("rationale", "")
        if action == "promote":
            cur = conn.execute(
                f"UPDATE findings SET status = 'candidate', judgment_rationale = ? "
                f"WHERE status = 'evidence' AND evidence_key = ? AND kind IN ({kind_marks})",
                (rationale, key, *DRAWING_FINDING_KINDS),
            )
            applied["promoted"] += cur.rowcount
        elif action == "dismiss":
            cur = conn.execute(
                f"UPDATE findings SET status = 'dismissed', judgment_rationale = ? "
                f"WHERE status = 'evidence' AND evidence_key = ? AND kind IN ({kind_marks})",
                (rationale, key, *DRAWING_FINDING_KINDS),
            )
            applied["dismissed"] += cur.rowcount
        elif action == "reclassify":
            new_kind = dec["kind"]
            if new_kind not in DRAWING_FINDING_KINDS:
                raise ValueError(f"Unknown finding kind: {new_kind}")
            cur = conn.execute(
                f"UPDATE findings SET status = 'candidate', kind = ?, "
                f"judgment_rationale = ? "
                f"WHERE status = 'evidence' AND evidence_key = ? AND kind IN ({kind_marks})",
                (new_kind, rationale, key, *DRAWING_FINDING_KINDS),
            )
            applied["reclassified"] += cur.rowcount
        else:
            raise ValueError(f"Unknown judgment action: {action}")

    for inv in payload.get("invariants", []):
        status = inv["status"]
        if status not in ("resolved", "overridden"):
            raise ValueError(f"Invalid invariant status: {status}")
        cur = conn.execute(
            "UPDATE invariant_results SET status = ?, rationale = ? "
            "WHERE id = ? AND check_name = ?",
            (status, inv.get("rationale", ""), inv["id"], CHECK_NAME),
        )
        applied["invariants"] += cur.rowcount

    return applied


def pending_evidence(conn: sqlite3.Connection) -> list[dict]:
    """Drawing findings still at status='evidence' (pending judgment)."""
    from qc_core.drawing.kinds import DRAWING_FINDING_KINDS

    kind_marks = ",".join("?" * len(DRAWING_FINDING_KINDS))
    rows = conn.execute(
        f"SELECT * FROM findings WHERE status = 'evidence' AND kind IN ({kind_marks}) "
        "ORDER BY kind, sheet_number",
        DRAWING_FINDING_KINDS,
    ).fetchall()
    return [dict(r) for r in rows]


def disputed_rows(conn: sqlite3.Connection) -> list[dict]:
    """Matrix rows for entity-keys whose channels disagree, grouped per key.

    A key is disputed when it is present in some channels and absent from
    others (given the channel exists for the project at all). This is the
    judgment node's worklist; clean keys never reach Claude.
    """
    rows = conn.execute(
        "SELECT entity_key, channel, volume_id, raw_value, page, detail "
        "FROM reconciliation_matrix WHERE check_name = ? "
        "ORDER BY entity_key, channel, volume_id",
        (CHECK_NAME,),
    ).fetchall()

    channels_present = {r["channel"] for r in rows}
    by_key: dict[str, list[dict]] = {}
    for r in rows:
        by_key.setdefault(r["entity_key"], []).append(dict(r))

    disputed = []
    for key, cells in sorted(by_key.items()):
        key_channels = {c["channel"] for c in cells}
        if key_channels != channels_present:
            disputed.append(
                {
                    "entity_key": key,
                    "present_in": sorted(key_channels),
                    "absent_from": sorted(channels_present - key_channels),
                    "cells": cells,
                }
            )
    return disputed
