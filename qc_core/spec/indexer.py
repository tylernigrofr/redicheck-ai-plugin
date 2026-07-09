"""Write spec extraction results into qc.sqlite and populate findings.

Multi-volume model (ADR-0013): TOC equivalence classes by section-number set,
findings computed against project-wide unions, not per-volume slices.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from qc_core.db import init_db
from qc_core.spec.config import DEFAULT_DIVISION_ROLLUP, DivisionRollupConfig
from qc_core.spec.kinds import SPEC_FINDING_KINDS
from qc_core.spec.parse import (
    analyze_pdf,
    is_admin,
    is_by_consultant,
    normalize_title_for_dup,
    section_number_near_match,
    titles_similar,
)


def _division_of(section_number: str) -> str:
    parts = section_number.split()
    return parts[0].zfill(2) if parts else ""


def _fingerprint(toc_sections: list[dict]) -> str:
    nums = sorted({s["number"] for s in toc_sections})
    return "|".join(nums)


def index_spec_pdf(
    conn: sqlite3.Connection,
    pdf_path: str | Path,
    *,
    force: bool = False,
) -> dict:
    """Parse one volume; write spec_volumes + spec_sections(body) + spec_related_refs.

    Does NOT write TOC rows into spec_sections (TOC goes to toc_class_sections in
    the project-level pass) and does NOT write findings.

    Skips re-parse when pdf mtime unchanged and force=False, returning
    `{"indexed": False, "reason": "unchanged", ...}`. Returns parsed toc_sections
    either way so the caller can group volumes into equivalence classes.
    """
    path = Path(pdf_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Spec PDF not found: {path}")

    mtime = path.stat().st_mtime
    existing = conn.execute(
        "SELECT id, pdf_mtime, toc_class_id FROM spec_volumes WHERE pdf_path = ?",
        (str(path),),
    ).fetchone()

    if existing and not force and abs(existing["pdf_mtime"] - mtime) < 0.001:
        toc_sections = []
        if existing["toc_class_id"] is not None:
            toc_sections = [
                {"number": r["number"], "title": r["title"], "toc_page": r["toc_page"]}
                for r in conn.execute(
                    """
                    SELECT number, title, toc_page FROM toc_class_sections
                    WHERE toc_class_id = ?
                    """,
                    (existing["toc_class_id"],),
                ).fetchall()
            ]
        return {
            "indexed": False,
            "reason": "unchanged",
            "volume_id": existing["id"],
            "pdf_path": str(path),
            "toc_sections": toc_sections,
        }

    result = analyze_pdf(str(path))
    if not result.get("success"):
        raise RuntimeError(result.get("error", "PDF analysis failed"))

    meta = result["meta"]
    toc_range = meta["toc_range"]
    has_full_toc = 1 if meta.get("toc_confirmed", True) else 0

    if existing:
        volume_id = existing["id"]
        conn.execute("DELETE FROM spec_related_refs WHERE volume_id = ?", (volume_id,))
        conn.execute("DELETE FROM spec_sections WHERE volume_id = ?", (volume_id,))
        conn.execute("DELETE FROM embedded_reports WHERE volume_id = ?", (volume_id,))
        conn.execute("DELETE FROM spec_placeholders WHERE volume_id = ?", (volume_id,))
        conn.execute(
            """
            UPDATE spec_volumes
            SET pdf_mtime = ?, page_count = ?, toc_start = ?, toc_end = ?,
                body_start = ?, has_full_toc = ?, indexed_at = datetime('now')
            WHERE id = ?
            """,
            (
                mtime,
                meta["total_pages"],
                toc_range["start"],
                toc_range["end"],
                meta["body_start_page"],
                has_full_toc,
                volume_id,
            ),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO spec_volumes (
                pdf_path, pdf_mtime, page_count, toc_start, toc_end, body_start,
                has_full_toc
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(path),
                mtime,
                meta["total_pages"],
                toc_range["start"],
                toc_range["end"],
                meta["body_start_page"],
                has_full_toc,
            ),
        )
        volume_id = cur.lastrowid

    for sec in result["body_sections"]:
        conn.execute(
            """
            INSERT INTO spec_sections (volume_id, number, title, source, page, occurrence)
            VALUES (?, ?, ?, 'body', ?, ?)
            """,
            (
                volume_id,
                sec["number"],
                sec.get("title"),
                sec.get("page"),
                sec.get("occurrence", 1),
            ),
        )

    for rep in result.get("embedded_reports", []):
        conn.execute(
            """
            INSERT OR IGNORE INTO embedded_reports (volume_id, number, title, page)
            VALUES (?, ?, ?, ?)
            """,
            (volume_id, rep["number"], rep.get("title"), rep.get("page")),
        )

    for ph in result.get("placeholders", []):
        conn.execute(
            """
            INSERT INTO spec_placeholders (volume_id, page, kind, token)
            VALUES (?, ?, ?, ?)
            """,
            (volume_id, ph["page"], ph["kind"], ph["token"]),
        )

    for ref in result["related_refs"]:
        conn.execute(
            """
            INSERT INTO spec_related_refs (
                volume_id, from_section, from_label, referenced_number,
                context_line, link_text, page
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                volume_id,
                ref.get("from_section"),
                ref.get("from_label"),
                ref["referenced_number"],
                ref.get("context_line"),
                ref.get("link_text"),
                ref["page"],
            ),
        )

    return {
        "indexed": True,
        "volume_id": volume_id,
        "pdf_path": str(path),
        "toc_sections": result["toc_sections"],
        "body_sections_count": len(result["body_sections"]),
        "related_refs_count": len(result["related_refs"]),
        "meta": meta,
    }


def _rebuild_toc_classes(
    conn: sqlite3.Connection,
    per_volume_toc: dict[int, list[dict]],
) -> dict[int, int]:
    """Group volumes by TOC section-set fingerprint; rewrite toc_classes
    and toc_class_sections; return {volume_id: toc_class_id}."""
    conn.execute("UPDATE spec_volumes SET toc_class_id = NULL")
    conn.execute("DELETE FROM toc_class_sections")
    conn.execute("DELETE FROM toc_classes")

    by_fp: dict[str, list[int]] = {}
    for vol_id, toc in per_volume_toc.items():
        by_fp.setdefault(_fingerprint(toc), []).append(vol_id)

    vol_to_class: dict[int, int] = {}
    for fp, member_vol_ids in by_fp.items():
        member_vol_ids.sort()
        rep_vol_id = member_vol_ids[0]
        rep_toc = per_volume_toc[rep_vol_id]
        cur = conn.execute(
            """
            INSERT INTO toc_classes (fingerprint, section_count, representative_volume_id)
            VALUES (?, ?, ?)
            """,
            (fp, len({s["number"] for s in rep_toc}), rep_vol_id),
        )
        class_id = cur.lastrowid
        for sec in rep_toc:
            conn.execute(
                """
                INSERT OR IGNORE INTO toc_class_sections
                    (toc_class_id, number, title, toc_page, occurrence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    class_id,
                    sec["number"],
                    sec.get("title"),
                    sec.get("toc_page"),
                    sec.get("occurrence", 1),
                ),
            )
        for vol_id in member_vol_ids:
            conn.execute(
                "UPDATE spec_volumes SET toc_class_id = ? WHERE id = ?",
                (class_id, vol_id),
            )
            vol_to_class[vol_id] = class_id
    return vol_to_class


def _detect_title_mismatches_across_volumes(
    conn: sqlite3.Connection,
    per_volume_toc: dict[int, list[dict]],
) -> None:
    """Within each equivalence class, flag sections whose titles diverge across
    member volumes. Emits 'title_mismatch_across_volumes' findings."""
    rows = conn.execute(
        "SELECT id, toc_class_id FROM spec_volumes WHERE toc_class_id IS NOT NULL"
    ).fetchall()
    by_class: dict[int, list[int]] = {}
    for r in rows:
        by_class.setdefault(r["toc_class_id"], []).append(r["id"])

    for class_id, vol_ids in by_class.items():
        if len(vol_ids) < 2:
            continue
        # number -> {vol_id: title}
        per_section: dict[str, dict[int, str]] = {}
        toc_pages: dict[tuple[str, int], int] = {}
        for vid in vol_ids:
            for sec in per_volume_toc.get(vid, []):
                title = (sec.get("title") or "").strip()
                if not title:
                    continue
                per_section.setdefault(sec["number"], {})[vid] = title
                toc_pages[(sec["number"], vid)] = sec.get("toc_page")
        for num, titles_by_vol in per_section.items():
            uniq = list({t.lower() for t in titles_by_vol.values()})
            if len(uniq) < 2:
                continue
            # check pairwise: if any pair is dissimilar, emit
            divergent = False
            vals = list(titles_by_vol.values())
            for i in range(len(vals)):
                for j in range(i + 1, len(vals)):
                    if not titles_similar(vals[i], vals[j]):
                        divergent = True
                        break
                if divergent:
                    break
            if not divergent:
                continue
            # emit one finding per volume showing its divergent title
            for vid, title in titles_by_vol.items():
                conn.execute(
                    """
                    INSERT INTO findings (
                        volume_id, kind, expected_action, severity,
                        section, title, toc_page, notes
                    ) VALUES (?, 'title_mismatch_across_volumes', 'info_only', 'low',
                              ?, ?, ?, ?)
                    """,
                    (
                        vid,
                        num,
                        title,
                        toc_pages.get((num, vid)),
                        f"toc_class={class_id}",
                    ),
                )


def _clear_spec_findings(conn: sqlite3.Connection) -> None:
    placeholders = ",".join("?" * len(SPEC_FINDING_KINDS))
    conn.execute(
        f"DELETE FROM findings WHERE kind IN ({placeholders})",
        SPEC_FINDING_KINDS,
    )


def compute_project_findings(
    conn: sqlite3.Connection,
    *,
    rollup_config: DivisionRollupConfig = DEFAULT_DIVISION_ROLLUP,
) -> None:
    """Project-level findings against unions across volumes (ADR-0013).

    Assumes spec_volumes / spec_sections(body) / spec_related_refs / toc_classes /
    toc_class_sections are all up to date for the current project state.
    """
    # #84: a Reviewer's dismiss/reclassify judgment on a candidate finding is
    # a durable Resolution (ADR-0024), not scoped to one evidence snapshot —
    # preserve it across the delete-then-reinsert recompute cycle below so a
    # plain reindex doesn't resurrect a finding the Reviewer already refuted.
    prior_judgments = {
        (r["evidence_key"], r["kind"]): (r["status"], r["judgment_rationale"])
        for r in conn.execute(
            f"SELECT evidence_key, kind, status, judgment_rationale FROM findings "
            f"WHERE kind IN ({','.join('?' * len(SPEC_FINDING_KINDS))}) "
            f"AND status = 'dismissed' AND evidence_key IS NOT NULL",
            SPEC_FINDING_KINDS,
        ).fetchall()
    }

    _clear_spec_findings(conn)

    # union(class TOC numbers) -> {number: (title, toc_page, representative_volume_id)}
    toc_rows = conn.execute(
        """
        SELECT tcs.number, tcs.title, tcs.toc_page, tc.representative_volume_id
        FROM toc_class_sections tcs
        JOIN toc_classes tc ON tc.id = tcs.toc_class_id
        """
    ).fetchall()
    toc_by_num: dict[str, sqlite3.Row] = {}
    for r in toc_rows:
        toc_by_num.setdefault(r["number"], r)  # first wins; numbers may repeat across classes

    # union(body) -> {number: (volume_id, page, title)}
    body_rows = conn.execute(
        "SELECT volume_id, number, title, page FROM spec_sections WHERE source = 'body'"
    ).fetchall()
    body_by_num: dict[str, sqlite3.Row] = {}
    for r in body_rows:
        body_by_num.setdefault(r["number"], r)

    toc_nums = {n for n in toc_by_num if not is_admin(n)}
    body_nums = {n for n in body_by_num if not is_admin(n)}
    all_known = set(toc_by_num) | set(body_by_num)

    # Section-completeness check (toc_not_in_body / body_not_in_toc) is only
    # applicable when the set actually has a specification TOC. On a TOC-less
    # manual the parser fabricates a phantom TOC from the first body pages and
    # the diff inverts into hundreds of false findings (issue #52). When no
    # volume carries a confirmed TOC, skip both completeness kinds and record a
    # single info note. broken_related_ref and duplicate checks are unaffected.
    project_has_toc = (
        conn.execute(
            "SELECT 1 FROM spec_volumes WHERE has_full_toc = 1 LIMIT 1"
        ).fetchone()
        is not None
    )

    body_divs = {_division_of(n) for n in body_nums}

    if project_has_toc:
        # Mis-numbered sections (#44): a body header whose title matches a TOC
        # entry but whose number differs is a single mis-numbering defect, not a
        # pair of orphans (toc_not_in_body + body_not_in_toc). Detect by
        # normalized-title match and suppress both orphans in favor of one
        # section_number_mismatch.
        mismatch_toc_nums, mismatch_body_nums = _detect_section_number_mismatches(
            conn, toc_by_num, body_by_num, toc_nums, body_nums
        )

        # Embedded non-CSI reports confirmed present via the PDF outline (#43):
        # keyed by number -> a representative (volume_id, page). Such a report is
        # listed in the TOC but has no CSI body header, so it would otherwise be
        # a false toc_not_in_body. When the outline confirms it is bound in,
        # downgrade.
        embedded_present: dict[str, sqlite3.Row] = {}
        for r in conn.execute(
            "SELECT volume_id, number, title, page FROM embedded_reports"
        ).fetchall():
            embedded_present.setdefault(r["number"], r)

        # toc_not_in_body (split out toc_by_consultant as info_only — not emitted)
        for num in sorted(toc_nums - body_nums - mismatch_toc_nums):
            row = toc_by_num[num]
            title = row["title"] or ""
            if is_by_consultant(title):
                continue
            if num in embedded_present:
                rep = embedded_present[num]
                conn.execute(
                    """
                    INSERT INTO findings (
                        volume_id, kind, expected_action, severity,
                        section, title, toc_page, body_page, notes
                    ) VALUES (?, 'embedded_report_present', 'info_only', 'low',
                              ?, ?, ?, ?, ?)
                    """,
                    (
                        rep["volume_id"],
                        num,
                        title,
                        row["toc_page"],
                        rep["page"],
                        "Embedded non-CSI document (e.g. a bound-in report) — "
                        "listed in the TOC and confirmed present in the set via "
                        "the PDF outline; has no CSI section body by design, so "
                        "not a toc_not_in_body defect.",
                    ),
                )
                continue
            conn.execute(
                """
                INSERT INTO findings (
                    volume_id, kind, expected_action, severity, section, title, toc_page
                ) VALUES (?, 'toc_not_in_body', 'emit_markup', 'medium', ?, ?, ?)
                """,
                (row["representative_volume_id"], num, title, row["toc_page"]),
            )

        # body_not_in_toc
        for num in sorted(body_nums - toc_nums - mismatch_body_nums):
            row = body_by_num[num]
            conn.execute(
                """
                INSERT INTO findings (
                    volume_id, kind, expected_action, severity, section, title, body_page
                ) VALUES (?, 'body_not_in_toc', 'emit_markup', 'high', ?, ?, ?)
                """,
                (row["volume_id"], num, row["title"], row["page"]),
            )
    else:
        # The NULL-volume_id case escapes the per-volume findings cleanup, so a
        # re-index would otherwise stack a duplicate row each run.
        conn.execute("DELETE FROM findings WHERE kind = 'spec_toc_absent'")
        rep = conn.execute(
            "SELECT id FROM spec_volumes ORDER BY id LIMIT 1"
        ).fetchone()
        conn.execute(
            """
            INSERT INTO findings (
                volume_id, kind, expected_action, severity, notes
            ) VALUES (?, 'spec_toc_absent', 'info_only', 'low', ?)
            """,
            (
                rep["id"] if rep else None,
                "No specification TOC found — section-completeness check "
                "(toc_not_in_body / body_not_in_toc) skipped. Related-reference "
                "and duplicate-section checks still ran.",
            ),
        )

    # Broken / typo refs: target not in union(all_known) and not admin
    refs = conn.execute(
        """
        SELECT volume_id, from_section, from_label, referenced_number,
               context_line, link_text, page
        FROM spec_related_refs
        """
    ).fetchall()

    # Title lookup for the IR classifier (#59): normalized title -> numbers.
    titles_by_norm: dict[str, set[str]] = {}
    for num, row in list(toc_by_num.items()) + list(body_by_num.items()):
        t = normalize_title_for_dup(row["title"] or "")
        if t:
            titles_by_norm.setdefault(t, set()).add(num)

    seen: set[tuple] = set()
    broken: list[sqlite3.Row] = []
    for r in refs:
        target = r["referenced_number"]
        if target in all_known or is_admin(target):
            continue
        key = (r["from_section"] or r["from_label"], target)
        if key in seen:
            continue
        seen.add(key)
        broken.append(r)

    # Division rollup: divisions referenced ≥ N times but with zero body presence
    broken_by_div: dict[str, list[sqlite3.Row]] = {}
    for r in broken:
        broken_by_div.setdefault(_division_of(r["referenced_number"]), []).append(r)
    rollup_divs: set[str] = set()
    for div, items in broken_by_div.items():
        if div not in body_divs and len(items) >= rollup_config.min_broken_refs:
            rollup_divs.add(div)

    for div in sorted(rollup_divs):
        rep_vol = broken_by_div[div][0]["volume_id"]
        comment = rollup_config.comment_template.format(division=div)
        conn.execute(
            """
            INSERT INTO findings (
                volume_id, kind, expected_action, severity, division, client_comment
            ) VALUES (?, 'division_referenced_but_not_included', 'emit_markup', 'high', ?, ?)
            """,
            (rep_vol, div, comment),
        )

    broken.sort(key=lambda r: (r["volume_id"], r["referenced_number"], r["page"]))
    broken_count_by_target: dict[tuple, int] = {}
    for r in broken:
        k = (r["volume_id"], r["referenced_number"])
        broken_count_by_target[k] = broken_count_by_target.get(k, 0) + 1
    emitted_targets: set[tuple] = set()

    for r in broken:
        div = _division_of(r["referenced_number"])
        target = r["referenced_number"]
        if div in rollup_divs and target not in rollup_config.rollup_emit_exceptions:
            kind = "broken_related_ref_div01" if div == "01" else "broken_related_ref"
            conn.execute(
                """
                INSERT INTO findings (
                    volume_id, kind, expected_action, severity,
                    from_section, from_label, to_section, source_page, context
                ) VALUES (?, ?, 'info_only', 'low', ?, ?, ?, ?, ?)
                """,
                (
                    r["volume_id"],
                    kind,
                    r["from_section"],
                    r["from_label"],
                    target,
                    r["page"],
                    r["context_line"],
                ),
            )
        else:
            # #59: volume-wide dedup — repeat refs to the same broken target
            # are recorded info_only; the earliest occurrence carries the
            # markup, tagged 'typical' so the comment reads accordingly.
            dedup_key = (r["volume_id"], target)
            is_first = dedup_key not in emitted_targets
            emitted_targets.add(dedup_key)

            ref_cls, suggestion = _classify_broken_ref(
                target, r["link_text"], all_known, titles_by_norm
            )
            tags = [ref_cls] if ref_cls else []
            if is_first and broken_count_by_target.get(dedup_key, 0) > 1:
                tags.append("typical")
            conn.execute(
                """
                INSERT INTO findings (
                    volume_id, kind, expected_action, severity,
                    from_section, from_label, to_section, source_page, context,
                    probable_match, ref_class, notes
                ) VALUES (?, 'broken_related_ref', ?, 'medium', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["volume_id"],
                    "emit_markup" if is_first else "info_only",
                    r["from_section"],
                    r["from_label"],
                    target,
                    r["page"],
                    r["context_line"],
                    suggestion,
                    ",".join(tags) or None,
                    None
                    if is_first
                    else f"Deduplicated: same broken target {target} already "
                    f"flagged earlier in this volume (kept first occurrence).",
                ),
            )

    _detect_duplicate_section_numbers(conn)
    _detect_incomplete_placeholders(conn)
    _reconcile_and_gate(conn)

    # Re-apply preserved dismiss judgments last, after every other status
    # write above — a Reviewer's dismissal always wins over a freshly
    # recomputed verdict for the same (evidence_key, kind).
    if prior_judgments:
        for (evidence_key, kind), (status, rationale) in prior_judgments.items():
            conn.execute(
                "UPDATE findings SET status = ?, judgment_rationale = ? "
                "WHERE evidence_key = ? AND kind = ?",
                (status, rationale, evidence_key, kind),
            )


def _reconcile_and_gate(conn: sqlite3.Connection) -> None:
    """ADR-0026 §2 spec instantiation: persist the reconciliation matrix, run
    the fail-loud invariants, and hold completeness conclusions on untrusted
    divisions at status='evidence' (pending judgment) rather than concluding
    them as Candidates."""
    from qc_core.spec import matrix as spec_matrix

    spec_matrix.build_matrix(conn)
    spec_matrix.evaluate_invariants(conn)

    untrusted = spec_matrix.tripped_division_scopes(conn)
    if not untrusted:
        return
    rows = conn.execute(
        "SELECT id, section FROM findings "
        "WHERE kind IN ('body_not_in_toc', 'toc_not_in_body') AND section IS NOT NULL"
    ).fetchall()
    for r in rows:
        if _division_of(r["section"]) in untrusted:
            conn.execute(
                "UPDATE findings SET status = 'evidence', evidence_key = ? WHERE id = ?",
                (r["section"], r["id"]),
            )


def _detect_incomplete_placeholders(conn: sqlite3.Connection) -> None:
    """Emit one callout per (volume, page, kind) for unfinished MasterSpec
    boilerplate (#61). A page repeating the same signal gets a "(typical)"
    callout; the first token anchors it. incomplete_placeholder (`<Insert …>`)
    is high precision; unresolved_option_bracket is already gated at parse time
    on same-line co-occurrence with an `<Insert …>`."""
    rows = conn.execute(
        "SELECT volume_id, page, kind, token FROM spec_placeholders "
        "ORDER BY volume_id, page, kind, id"
    ).fetchall()

    grouped: dict[tuple[int, int, str], list[str]] = {}
    for r in rows:
        grouped.setdefault((r["volume_id"], r["page"], r["kind"]), []).append(
            r["token"]
        )

    for (volume_id, page, kind), tokens in grouped.items():
        typical = len(tokens) > 1
        if kind == "incomplete_placeholder":
            comment = "Incomplete (typical)" if typical else "Incomplete"
        else:
            comment = "Delete, typical" if typical else "Delete"
        notes = (
            f"{len(tokens)} occurrence(s) on p.{page}; e.g. {tokens[0]}"
            if typical
            else tokens[0]
        )
        conn.execute(
            """
            INSERT INTO findings (
                volume_id, kind, expected_action, severity,
                body_page, client_comment, context, notes
            ) VALUES (?, ?, 'emit_markup', 'medium', ?, ?, ?, ?)
            """,
            (volume_id, kind, page, comment, tokens[0], notes),
        )


def _digit_edit_le1(a: str, b: str) -> bool:
    """Digit strings within one substitution, insertion, or deletion."""
    if a == b:
        return True
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if abs(len(a) - len(b)) != 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = j = 0
    skipped = False
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
        elif skipped:
            return False
        else:
            skipped = True
            j += 1
    return True


def _classify_broken_ref(
    target: str,
    link_text: str | None,
    all_known: set[str],
    titles_by_norm: dict[str, set[str]],
) -> tuple[str | None, str | None]:
    """Classify a broken cross-reference target (#59).

    Returns (ref_class, suggested_number):
      'ir'         — the captured link text matches exactly one known section
                     title in the target's division ("Metal Stairs" exists,
                     just under 05 51 00 not 05 51 13)
      'suffix'     — target is absent but exactly one `target.NN` child exists
      'digit_typo' — exactly one known section sits within digit edit
                     distance 1 (07 27 260 -> 07 27 26; 20 05 00 -> 22 05 00)
      (None, None) — plain CNL.
    """
    if link_text:
        t = normalize_title_for_dup(link_text)
        candidates = {
            n
            for n in titles_by_norm.get(t, set())
            if n.split()[0] == target.split()[0]
        }
        if len(candidates) == 1:
            return "ir", candidates.pop()
    children = sorted(k for k in all_known if k.startswith(target + "."))
    if len(children) == 1:
        return "suffix", children[0]
    td = re.sub(r"\D", "", target)
    near = sorted(
        k for k in all_known if _digit_edit_le1(td, re.sub(r"\D", "", k))
    )
    if len(near) == 1:
        return "digit_typo", near[0]
    return None, None


def _detect_section_number_mismatches(
    conn: sqlite3.Connection,
    toc_by_num: dict[str, sqlite3.Row],
    body_by_num: dict[str, sqlite3.Row],
    toc_nums: set[str],
    body_nums: set[str],
) -> tuple[set[str], set[str]]:
    """Pair a TOC-only section with a body-only section sharing its title (#44).

    When a body header carries the wrong CSI number but the right title (e.g.
    "CONCRETE CURING" at 03 60 00, where the TOC lists it as 03 39 00), the
    generic diff yields two orphans. Match them by normalized title and emit a
    single `section_number_mismatch`; return the (toc_nums, body_nums) that the
    caller should drop from the toc_not_in_body / body_not_in_toc buckets.

    Only unambiguous 1:1 title matches are paired — if a title resolves to more
    than one orphan on either side, both are left as plain orphans.

    A second pass (#60) pairs remaining orphans whose *numbers* are near
    variants — a `.NN` suffix child or a single-digit typo — provided their
    titles are compatible. Those carry a match basis in `context` ('suffix' /
    'digit_typo') so emit can produce a two-sided AVW callout instead of the
    one-sided "should be" correction.
    """
    toc_only = toc_nums - body_nums
    body_only = body_nums - toc_nums

    matched_toc: set[str] = set()
    matched_body: set[str] = set()

    def _insert(toc_num: str, body_num: str, basis: str, notes: str) -> None:
        matched_toc.add(toc_num)
        matched_body.add(body_num)
        trow = toc_by_num[toc_num]
        brow = body_by_num[body_num]
        title = (trow["title"] or brow["title"] or "").strip()
        conn.execute(
            """
            INSERT INTO findings (
                volume_id, kind, expected_action, severity,
                section, title, body_page, toc_page, probable_match, context, notes
            ) VALUES (?, 'section_number_mismatch', 'emit_markup', 'high',
                      ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                brow["volume_id"],
                body_num,
                title,
                brow["page"],
                trow["toc_page"],
                toc_num,
                basis,
                notes,
            ),
        )

    body_by_title: dict[str, list[str]] = {}
    for num in body_only:
        t = normalize_title_for_dup(body_by_num[num]["title"] or "")
        if t:
            body_by_title.setdefault(t, []).append(num)

    for toc_num in sorted(toc_only):
        t = normalize_title_for_dup(toc_by_num[toc_num]["title"] or "")
        if not t:
            continue
        candidates = body_by_title.get(t, [])
        if len(candidates) != 1:
            continue  # ambiguous (or none) — leave as orphans
        body_num = candidates[0]
        if body_num in matched_body:
            continue
        trow = toc_by_num[toc_num]
        brow = body_by_num[body_num]
        title = (trow["title"] or brow["title"] or "").strip()
        # Even on a title match, a near-variant number (suffix/digit typo)
        # means neither side is provably right — record that basis so emit
        # produces the two-sided AVW callout instead of a correction.
        basis = section_number_near_match(toc_num, body_num) or "title"
        if basis == "title":
            notes = (
                f'Section title "{title}" is numbered {body_num} in the body '
                f'(p.{brow["page"]}) but {toc_num} in the TOC (p.{trow["toc_page"]}). '
                f"Body section number is likely wrong; should be {toc_num}."
            )
        else:
            notes = (
                f"TOC lists {toc_num} (p.{trow['toc_page']}) while the body carries "
                f"{body_num} (p.{brow['page']}) — a near-variant number under the "
                f"same title. Which side is correct needs reviewer confirmation "
                f"(AVW both)."
            )
        _insert(toc_num, body_num, basis, notes)

    # Pass 2 (#60): number-proximity pairs among the orphans the title pass
    # left behind. Requires an unambiguous 1:1 near-match on both sides and
    # compatible titles (titles_similar accepts a blank side).
    near_by_toc: dict[str, list[tuple[str, str]]] = {}
    near_by_body: dict[str, int] = {}
    for toc_num in sorted(toc_only - matched_toc):
        for body_num in sorted(body_only - matched_body):
            basis = section_number_near_match(toc_num, body_num)
            if basis is None:
                continue
            if not titles_similar(
                toc_by_num[toc_num]["title"] or "", body_by_num[body_num]["title"] or ""
            ):
                continue
            near_by_toc.setdefault(toc_num, []).append((body_num, basis))
            near_by_body[body_num] = near_by_body.get(body_num, 0) + 1

    for toc_num, pairs in sorted(near_by_toc.items()):
        if len(pairs) != 1:
            continue
        body_num, basis = pairs[0]
        if near_by_body[body_num] != 1 or body_num in matched_body:
            continue
        trow = toc_by_num[toc_num]
        brow = body_by_num[body_num]
        what = (
            "a .NN suffix variant" if basis == "suffix" else "a single-digit variant"
        )
        _insert(
            toc_num,
            body_num,
            basis,
            f"TOC lists {toc_num} (p.{trow['toc_page']}) while the body carries "
            f"{body_num} (p.{brow['page']}) — {what} of the same section. "
            f"Which side is correct needs reviewer confirmation (AVW both).",
        )

    return matched_toc, matched_body


def _detect_duplicate_section_numbers(conn: sqlite3.Connection) -> None:
    """Flag CSI section numbers reused by two distinct sections in a volume's
    body (#45). Same normalized title -> duplicate_section_number_and_name
    (high); differing titles -> duplicate_section_number (medium). Anchored on
    the TOC page (where reviewers mark it) when the number is listed there."""
    rows = conn.execute(
        """
        SELECT volume_id, number, title, page, occurrence
        FROM spec_sections
        WHERE source = 'body'
        ORDER BY volume_id, number, occurrence
        """
    ).fetchall()

    by_vol_num: dict[tuple[int, str], list[sqlite3.Row]] = {}
    for r in rows:
        by_vol_num.setdefault((r["volume_id"], r["number"]), []).append(r)

    toc_page_by_num: dict[str, int] = {}
    toc_titles_by_num: dict[str, list[str]] = {}
    for r in conn.execute(
        "SELECT number, title, toc_page FROM toc_class_sections"
    ).fetchall():
        if r["toc_page"] is not None:
            toc_page_by_num.setdefault(r["number"], r["toc_page"])
        toc_titles_by_num.setdefault(r["number"], []).append((r["title"] or "").strip())

    for (volume_id, number), occs in by_vol_num.items():
        if len(occs) < 2 or is_admin(number):
            continue
        body_titles = [(o["title"] or "").strip() for o in occs]
        toc_titles = [t for t in toc_titles_by_num.get(number, []) if t]
        # Classify by the TOC titles when the number is listed there more than
        # once (that's what reviewers read); the two body SECTION-header lines
        # are often identical even when the TOC entries differ. Fall back to the
        # body titles when the TOC doesn't list the number twice.
        if len(toc_titles) >= 2:
            naming_titles = toc_titles
        else:
            naming_titles = [t for t in body_titles if t]
        same_name = len({normalize_title_for_dup(t) for t in naming_titles}) <= 1
        kind = (
            "duplicate_section_number_and_name"
            if same_name
            else "duplicate_section_number"
        )
        severity = "high" if same_name else "medium"
        pages = ", ".join(f"p.{o['page']}" for o in occs)
        shown_titles = toc_titles if len(toc_titles) >= 2 else body_titles
        title_list = " / ".join(f'"{t}"' for t in shown_titles if t) or "(untitled)"
        label = "and name " if same_name else ""
        notes = (
            f"Duplicate section number {label}{number}: {len(occs)} body sections "
            f"({pages}) — {title_list}."
        )
        toc_page = toc_page_by_num.get(number)
        conn.execute(
            """
            INSERT INTO findings (
                volume_id, kind, expected_action, severity,
                section, title, body_page, toc_page, notes
            ) VALUES (?, ?, 'emit_markup', ?, ?, ?, ?, ?, ?)
            """,
            (
                volume_id,
                kind,
                severity,
                number,
                body_titles[0] or None,
                occs[0]["page"],
                toc_page,
                notes,
            ),
        )


def index_project(
    project_folder: str | Path,
    *,
    force: bool = False,
    rollup_config: DivisionRollupConfig = DEFAULT_DIVISION_ROLLUP,
) -> list[dict]:
    """Index all discovered spec PDFs into qc.sqlite in project_folder.

    Always rebuilds project-level state (toc_classes, findings) so multi-volume
    union semantics stay correct.
    """
    from qc_core.discovery import discover_spec_pdfs, qc_sqlite_path

    root = Path(project_folder)
    db_path = qc_sqlite_path(root)
    conn = init_db(db_path)
    try:
        volumes = discover_spec_pdfs(root)
        if not volumes:
            raise FileNotFoundError(f"No spec PDFs found in {root}")

        per_volume_toc: dict[int, list[dict]] = {}
        summaries: list[dict] = []
        any_reindexed = False
        for vol in volumes:
            summary = index_spec_pdf(conn, vol.path, force=force)
            per_volume_toc[summary["volume_id"]] = summary["toc_sections"]
            summaries.append(summary)
            if summary.get("indexed"):
                any_reindexed = True

        # Rebuild project-level state only when at least one volume re-parsed,
        # or when no toc_classes exist yet (first run after migration).
        has_classes = conn.execute(
            "SELECT 1 FROM toc_classes LIMIT 1"
        ).fetchone() is not None
        if any_reindexed or not has_classes:
            _rebuild_toc_classes(conn, per_volume_toc)
            _detect_title_mismatches_across_volumes(conn, per_volume_toc)
            compute_project_findings(conn, rollup_config=rollup_config)
        conn.commit()
        return summaries
    finally:
        conn.close()


def needs_reindex(project_folder: str | Path) -> bool:
    """True if qc.sqlite missing or any spec PDF newer than indexed mtime."""
    from qc_core.discovery import discover_spec_pdfs, qc_sqlite_path

    root = Path(project_folder)
    db_path = qc_sqlite_path(root)
    if not db_path.is_file():
        return True

    conn = init_db(db_path)
    try:
        for vol in discover_spec_pdfs(root):
            row = conn.execute(
                "SELECT pdf_mtime FROM spec_volumes WHERE pdf_path = ?",
                (str(vol.path.resolve()),),
            ).fetchone()
            mtime = vol.path.stat().st_mtime
            if not row or abs(row["pdf_mtime"] - mtime) >= 0.001:
                return True
        return False
    finally:
        conn.close()
