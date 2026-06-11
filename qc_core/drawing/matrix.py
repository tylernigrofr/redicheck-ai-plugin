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

    return all_invariants(conn)


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


def apply_judgments(conn: sqlite3.Connection, payload: dict) -> dict:
    """Apply a judgment node's schema-constrained decisions (ADR-0026 §3-4).

    Payload shape:
        {
          "decisions": [
            {"evidence_key": str, "action": "promote"|"dismiss"|"reclassify",
             "kind": str (required for reclassify), "rationale": str}
          ],
          "invariants": [
            {"id": int, "status": "resolved"|"overridden", "rationale": str}
          ]
        }

    Decisions act on findings currently at status='evidence' for the given
    entity-key. Rationale is recorded on the row (auditable, re-verifiable).
    Returns counts of applied changes.
    """
    from qc_core.drawing.kinds import DRAWING_FINDING_KINDS

    applied = {"promoted": 0, "dismissed": 0, "reclassified": 0, "invariants": 0}
    kind_marks = ",".join("?" * len(DRAWING_FINDING_KINDS))

    for dec in payload.get("decisions", []):
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
