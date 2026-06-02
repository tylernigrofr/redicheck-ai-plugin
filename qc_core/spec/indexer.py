"""Write spec extraction results into qc.sqlite and populate findings.

Multi-volume model (ADR-0013): TOC equivalence classes by section-number set,
findings computed against project-wide unions, not per-volume slices.
"""

from __future__ import annotations

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

    if existing:
        volume_id = existing["id"]
        conn.execute("DELETE FROM spec_related_refs WHERE volume_id = ?", (volume_id,))
        conn.execute("DELETE FROM spec_sections WHERE volume_id = ?", (volume_id,))
        conn.execute("DELETE FROM embedded_reports WHERE volume_id = ?", (volume_id,))
        conn.execute(
            """
            UPDATE spec_volumes
            SET pdf_mtime = ?, page_count = ?, toc_start = ?, toc_end = ?,
                body_start = ?, indexed_at = datetime('now')
            WHERE id = ?
            """,
            (
                mtime,
                meta["total_pages"],
                toc_range["start"],
                toc_range["end"],
                meta["body_start_page"],
                volume_id,
            ),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO spec_volumes (
                pdf_path, pdf_mtime, page_count, toc_start, toc_end, body_start
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(path),
                mtime,
                meta["total_pages"],
                toc_range["start"],
                toc_range["end"],
                meta["body_start_page"],
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

    for ref in result["related_refs"]:
        conn.execute(
            """
            INSERT INTO spec_related_refs (
                volume_id, from_section, from_label, referenced_number,
                context_line, page
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                volume_id,
                ref.get("from_section"),
                ref.get("from_label"),
                ref["referenced_number"],
                ref.get("context_line"),
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

    # Mis-numbered sections (#44): a body header whose title matches a TOC entry
    # but whose number differs is a single mis-numbering defect, not a pair of
    # orphans (toc_not_in_body + body_not_in_toc). Detect by normalized-title
    # match and suppress both orphans in favor of one section_number_mismatch.
    mismatch_toc_nums, mismatch_body_nums = _detect_section_number_mismatches(
        conn, toc_by_num, body_by_num, toc_nums, body_nums
    )

    # Embedded non-CSI reports confirmed present via the PDF outline (#43): keyed
    # by number -> a representative (volume_id, page). Such a report is listed in
    # the TOC but has no CSI body header, so it would otherwise be a false
    # toc_not_in_body. When the outline confirms it is bound in, downgrade.
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
                    "Embedded non-CSI document (e.g. a bound-in report) — listed "
                    "in the TOC and confirmed present in the set via the PDF "
                    "outline; has no CSI section body by design, so not a "
                    "toc_not_in_body defect.",
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
    body_divs = {_division_of(n) for n in body_nums}
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

    # Broken / typo refs: target not in union(all_known) and not admin
    refs = conn.execute(
        """
        SELECT volume_id, from_section, from_label, referenced_number,
               context_line, page
        FROM spec_related_refs
        """
    ).fetchall()

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
            conn.execute(
                """
                INSERT INTO findings (
                    volume_id, kind, expected_action, severity,
                    from_section, from_label, to_section, source_page, context
                ) VALUES (?, 'broken_related_ref', 'emit_markup', 'medium', ?, ?, ?, ?, ?)
                """,
                (
                    r["volume_id"],
                    r["from_section"],
                    r["from_label"],
                    r["referenced_number"],
                    r["page"],
                    r["context_line"],
                ),
            )

    _detect_duplicate_section_numbers(conn)


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
    """
    toc_only = toc_nums - body_nums
    body_only = body_nums - toc_nums

    body_by_title: dict[str, list[str]] = {}
    for num in body_only:
        t = normalize_title_for_dup(body_by_num[num]["title"] or "")
        if t:
            body_by_title.setdefault(t, []).append(num)

    matched_toc: set[str] = set()
    matched_body: set[str] = set()
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
        matched_toc.add(toc_num)
        matched_body.add(body_num)

        trow = toc_by_num[toc_num]
        brow = body_by_num[body_num]
        title = (trow["title"] or brow["title"] or "").strip()
        notes = (
            f'Section title "{title}" is numbered {body_num} in the body '
            f'(p.{brow["page"]}) but {toc_num} in the TOC (p.{trow["toc_page"]}). '
            f"Body section number is likely wrong; should be {toc_num}."
        )
        conn.execute(
            """
            INSERT INTO findings (
                volume_id, kind, expected_action, severity,
                section, title, body_page, toc_page, probable_match, notes
            ) VALUES (?, 'section_number_mismatch', 'emit_markup', 'high',
                      ?, ?, ?, ?, ?, ?)
            """,
            (
                brow["volume_id"],
                body_num,
                title,
                brow["page"],
                trow["toc_page"],
                toc_num,
                notes,
            ),
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
