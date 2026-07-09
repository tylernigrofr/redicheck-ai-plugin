"""Reconciliation matrix + fail-loud invariants for the spec-check (ADR-0026 §2).

The spec instantiation of the ADR-0026 harness. Channels are {TOC, body,
related-ref targets} (ADR-0026 §5); the entity-key is the CSI section number.
The matrix is the Evidence artifact: one row per (section, channel, volume)
recording present with provenance, computed deterministically and persisted
without a verdict. Invariants are deterministic queries over it that catch the
silent parse failures #52 lives in — a volume whose TOC channel parsed zero
sections while a body exists (a phantom-TOC trap), or a division present in the
body with zero TOC coverage. A tripped invariant marks its scope untrusted
until a judgment node resolves it or the Reviewer overrides it (ADR-0024).
"""

from __future__ import annotations

import json
import sqlite3

from qc_core.spec.kinds import SPEC_FINDING_KINDS
from qc_core.spec.parse import is_admin

CHECK_NAME = "spec-check"

# Channels for the spec instantiation of the matrix (ADR-0026 §5).
CHANNEL_TOC = "toc"
CHANNEL_BODY = "body"
CHANNEL_RELATED_REF = "related_ref_target"

# A division-scoped invariant trips only past this floor so a one-off omission
# doesn't mark a whole project untrusted; below it the gap still surfaces as an
# ordinary body_not_in_toc Candidate.
DIVISION_MIN_BODY = 3

# Reconciliation kinds whose conclusion depends on TOC/body parse-completeness;
# these are the rows held at Evidence on an untrusted scope.
_RECONCILIATION_KINDS = ("body_not_in_toc", "toc_not_in_body")


def _division_of(section_number: str) -> str:
    parts = (section_number or "").split()
    return parts[0].zfill(2) if parts else ""


def build_matrix(conn: sqlite3.Connection) -> int:
    """Rebuild the spec-check reconciliation matrix from indexed data.

    Returns the number of matrix rows written. TOC rows are attributed to each
    class's representative volume; body and related-ref rows to the volume they
    were parsed from.
    """
    conn.execute(
        "DELETE FROM reconciliation_matrix WHERE check_name = ?", (CHECK_NAME,)
    )

    rows_written = 0

    def _write(entity_key, channel, volume_id, raw_value, page, detail=None):
        nonlocal rows_written
        cursor = conn.execute(
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
        rows_written += cursor.rowcount

    for row in conn.execute(
        """
        SELECT tcs.number, tcs.title, tcs.toc_page, tc.representative_volume_id
        FROM toc_class_sections tcs
        JOIN toc_classes tc ON tc.id = tcs.toc_class_id
        """
    ).fetchall():
        _write(
            row["number"],
            CHANNEL_TOC,
            row["representative_volume_id"],
            row["number"],
            row["toc_page"],
            {"title": row["title"]} if row["title"] else None,
        )

    for row in conn.execute(
        "SELECT volume_id, number, title, page FROM spec_sections WHERE source = 'body'"
    ).fetchall():
        _write(
            row["number"],
            CHANNEL_BODY,
            row["volume_id"],
            row["number"],
            row["page"],
            {"title": row["title"]} if row["title"] else None,
        )

    for row in conn.execute(
        "SELECT volume_id, referenced_number, page FROM spec_related_refs"
    ).fetchall():
        _write(
            row["referenced_number"],
            CHANNEL_RELATED_REF,
            row["volume_id"],
            row["referenced_number"],
            row["page"],
        )

    return rows_written


def evaluate_invariants(conn: sqlite3.Connection) -> list[dict]:
    """Evaluate the spec invariants over the persisted matrix.

    Existing 'resolved'/'overridden' rows are preserved across re-evaluation (a
    Resolution persists, ADR-0024); 'tripped' rows are recomputed. Returns all
    invariant rows for the check, freshly evaluated.
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

    # Per-volume body counts and confirmed-TOC flags.
    volumes = conn.execute(
        "SELECT id, has_full_toc FROM spec_volumes ORDER BY id"
    ).fetchall()
    body_by_volume: dict[int, int] = {}
    for r in conn.execute(
        "SELECT volume_id, COUNT(*) AS n FROM spec_sections "
        "WHERE source = 'body' GROUP BY volume_id"
    ).fetchall():
        body_by_volume[r["volume_id"]] = r["n"]

    project_has_toc = any(v["has_full_toc"] for v in volumes)

    # toc_channel_empty: a volume with a body but no confirmed TOC. The #52
    # phantom-TOC trap — discovery must surface this as a tripped invariant, not
    # fabricate a TOC from the first body pages.
    for v in volumes:
        if not v["has_full_toc"] and body_by_volume.get(v["id"], 0) >= DIVISION_MIN_BODY:
            _trip(
                "toc_channel_empty",
                str(v["id"]),
                {"body_sections": body_by_volume.get(v["id"], 0)},
            )

    # division_absent_from_toc: a division well-represented in the body with zero
    # TOC coverage, on a project that does have a TOC. Already rolls up as
    # body_not_in_toc findings; here it also gates (ADR-0026 §6a).
    if project_has_toc:
        toc_divs: set[str] = set()
        for r in conn.execute("SELECT number FROM toc_class_sections").fetchall():
            if not is_admin(r["number"]):
                toc_divs.add(_division_of(r["number"]))

        body_div_sections: dict[str, set[str]] = {}
        for r in conn.execute(
            "SELECT number FROM spec_sections WHERE source = 'body'"
        ).fetchall():
            if is_admin(r["number"]):
                continue
            body_div_sections.setdefault(_division_of(r["number"]), set()).add(
                r["number"]
            )

        for div, sections in sorted(body_div_sections.items()):
            if len(sections) >= DIVISION_MIN_BODY and div not in toc_divs:
                _trip(
                    "division_absent_from_toc",
                    div,
                    {
                        "body_sections": len(sections),
                        "sample": sorted(sections)[:5],
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
    """All scopes whose invariants are tripped and unresolved."""
    rows = conn.execute(
        "SELECT scope FROM invariant_results "
        "WHERE check_name = ? AND status = 'tripped'",
        (CHECK_NAME,),
    ).fetchall()
    return {r["scope"] for r in rows if r["scope"]}


def tripped_division_scopes(conn: sqlite3.Connection) -> set[str]:
    """Divisions held untrusted by a tripped `division_absent_from_toc`."""
    rows = conn.execute(
        "SELECT scope FROM invariant_results "
        "WHERE check_name = ? AND status = 'tripped' "
        "AND invariant = 'division_absent_from_toc'",
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

    Promote acts only on status='evidence' findings. Dismiss and reclassify
    also act on status='candidate' findings (#84) — a Reviewer-refuted
    Candidate needs the same recorded resolution path as an Evidence row, not
    just Evidence-status findings. Rationale is recorded on the row
    (auditable, re-verifiable). Returns counts of applied changes.
    """
    applied = {"promoted": 0, "dismissed": 0, "reclassified": 0, "invariants": 0}
    kind_marks = ",".join("?" * len(SPEC_FINDING_KINDS))

    for dec in payload.get("decisions", []):
        key = dec["evidence_key"]
        action = dec["action"]
        rationale = dec.get("rationale", "")
        if action == "promote":
            cur = conn.execute(
                f"UPDATE findings SET status = 'candidate', judgment_rationale = ? "
                f"WHERE status = 'evidence' AND evidence_key = ? AND kind IN ({kind_marks})",
                (rationale, key, *SPEC_FINDING_KINDS),
            )
            applied["promoted"] += cur.rowcount
        elif action == "dismiss":
            cur = conn.execute(
                f"UPDATE findings SET status = 'dismissed', judgment_rationale = ? "
                f"WHERE status IN ('evidence', 'candidate') AND evidence_key = ? "
                f"AND kind IN ({kind_marks})",
                (rationale, key, *SPEC_FINDING_KINDS),
            )
            applied["dismissed"] += cur.rowcount
        elif action == "reclassify":
            new_kind = dec["kind"]
            if new_kind not in SPEC_FINDING_KINDS:
                raise ValueError(f"Unknown finding kind: {new_kind}")
            cur = conn.execute(
                f"UPDATE findings SET status = 'candidate', kind = ?, "
                f"judgment_rationale = ? "
                f"WHERE status IN ('evidence', 'candidate') AND evidence_key = ? "
                f"AND kind IN ({kind_marks})",
                (new_kind, rationale, key, *SPEC_FINDING_KINDS),
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
    """Spec findings still at status='evidence' (pending judgment)."""
    kind_marks = ",".join("?" * len(SPEC_FINDING_KINDS))
    rows = conn.execute(
        f"SELECT * FROM findings WHERE status = 'evidence' AND kind IN ({kind_marks}) "
        "ORDER BY kind, section",
        SPEC_FINDING_KINDS,
    ).fetchall()
    return [dict(r) for r in rows]


def disputed_rows(conn: sqlite3.Connection) -> list[dict]:
    """Matrix rows for sections whose channels disagree, grouped per key.

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
