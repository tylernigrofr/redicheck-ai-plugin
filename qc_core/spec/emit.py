"""Build the emit manifest and write PDF annotations for spec-check.

`build_manifest()` returns a JSON-serializable list of entries (useful for
preview/audit). `emit_to_pdf()` writes those entries as PDF annotations
directly via PyMuPDF (ADR-0012, supersedes the MCP emit path for mass-emit).
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Iterable

from qc_core import markup
from qc_core.markup import EmitResult

SUBJECT_PREFIX = "spec-check"

SECTION_FORMATS = ("XX XX XX", "XX XXXX", "XXXXXX")
_FORMAT_PATTERNS = {
    "XX XX XX": re.compile(r"\b\d{2} \d{2} \d{2}\b"),
    "XX XXXX": re.compile(r"\b\d{2} \d{4}\b"),
    "XXXXXX": re.compile(r"(?<!\d)\d{6}(?!\d)"),
}


def format_section(canonical: str, fmt: str) -> str:
    """Render a canonical `"NN NN NN[ .NN]"` section number in the given on-page style."""
    if not canonical:
        return canonical
    parts = canonical.split()
    if len(parts) < 3:
        return canonical
    head = parts[:3]
    tail = parts[3:]
    if fmt == "XX XXXX":
        base = f"{head[0]} {head[1]}{head[2]}"
    elif fmt == "XXXXXX":
        base = "".join(head)
    else:
        base = " ".join(head)
    if tail:
        return base + "." + ".".join(tail)
    return base


def detect_section_format(pdf_path: Path | str, toc_start: int, toc_end: int) -> str:
    """Pick the dominant section-number style by regex-scanning TOC pages.

    Falls back to canonical "XX XX XX" when no recognised pattern is found.
    """
    import fitz

    doc = fitz.open(pdf_path)
    try:
        text_parts: list[str] = []
        last = min(toc_end, doc.page_count)
        for p in range(max(0, toc_start - 1), last):
            text_parts.append(doc[p].get_text())
    finally:
        doc.close()
    text = "\n".join(text_parts)
    counts = {fmt: len(pat.findall(text)) for fmt, pat in _FORMAT_PATTERNS.items()}
    if all(v == 0 for v in counts.values()):
        return "XX XX XX"
    return max(counts, key=lambda k: counts[k])

_SUBJECT_BY_KIND = {
    "broken_related_ref": f"{SUBJECT_PREFIX}:broken-related-ref",
    "body_not_in_toc": f"{SUBJECT_PREFIX}:body-not-in-toc",
    "toc_not_in_body": f"{SUBJECT_PREFIX}:toc-not-in-body",
    "section_number_mismatch": f"{SUBJECT_PREFIX}:section-number-mismatch",
    "division_referenced_but_not_included": f"{SUBJECT_PREFIX}:division-excluded",
    "duplicate_section_number": f"{SUBJECT_PREFIX}:duplicate-section-number",
    "duplicate_section_number_and_name": f"{SUBJECT_PREFIX}:duplicate-section-number-and-name",
    "incomplete_placeholder": f"{SUBJECT_PREFIX}:incomplete-placeholder",
    "unresolved_option_bracket": f"{SUBJECT_PREFIX}:unresolved-option-bracket",
}
_DIVISION_MISSING_SUBJECT = f"{SUBJECT_PREFIX}:division-missing-from-toc"


def section_variants(num: str) -> list[str]:
    """On-page string variants for a CSI section number.

    The indexer normalises section numbers to `"NN NN NN"` (or `"NN NN NN.NN"`
    for 4-part), but specs in the wild use compact and no-space forms. We try
    each variant in order of canonicality.
    """
    if not num:
        return []
    s = num.strip()
    out = [s]
    parts = s.split()
    if len(parts) >= 3:
        head = parts[:3]
        tail = parts[3:]
        joined = f"{head[0]} {head[1]}{head[2]}"
        if tail:
            joined = f"{joined}.{'.'.join(tail).lstrip('.')}" if any("." in t for t in tail) else f"{joined} {' '.join(tail)}"
        if joined not in out:
            out.append(joined)
        nospace = "".join(head) + ("".join(tail) if tail else "")
        if nospace not in out:
            out.append(nospace)
    return out


def adjacent_toc_section(missing: str, toc_numbers: list[str]) -> str | None:
    """Pick the alphabetically-adjacent TOC section to anchor a body_not_in_toc.

    Sort all TOC sections + the missing one; return the predecessor (or
    successor if `missing` sorts before everything).
    """
    if not toc_numbers:
        return None
    ordered = sorted(set(toc_numbers))
    pred: str | None = None
    for n in ordered:
        if n < missing:
            pred = n
        else:
            break
    if pred is not None:
        return pred
    return ordered[0]


def _toc_numbers(conn: sqlite3.Connection, volume_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT tcs.number
        FROM toc_class_sections tcs
        JOIN spec_volumes sv ON sv.toc_class_id = tcs.toc_class_id
        WHERE sv.id = ?
        """,
        (volume_id,),
    ).fetchall()
    return [r[0] for r in rows]


def _toc_page_of(conn: sqlite3.Connection, volume_id: int, section: str) -> int | None:
    row = conn.execute(
        """
        SELECT tcs.toc_page
        FROM toc_class_sections tcs
        JOIN spec_volumes sv ON sv.toc_class_id = tcs.toc_class_id
        WHERE sv.id = ? AND tcs.number = ?
        """,
        (volume_id, section),
    ).fetchone()
    return row[0] if row else None


def _toc_start(conn: sqlite3.Connection, volume_id: int) -> int:
    row = conn.execute(
        "SELECT toc_start FROM spec_volumes WHERE id = ?", (volume_id,)
    ).fetchone()
    return int(row[0]) if row else 1


def _toc_range(conn: sqlite3.Connection, volume_id: int) -> tuple[int, int]:
    row = conn.execute(
        "SELECT toc_start, toc_end FROM spec_volumes WHERE id = ?", (volume_id,)
    ).fetchone()
    if not row:
        return (1, 1)
    return (int(row[0]), int(row[1] or row[0]))


def _anchor_pages(
    conn: sqlite3.Connection, volume_id: int, anchor_page: int
) -> list[int]:
    """Anchor page first, then the volume's full TOC range as fallback.

    Stored toc_page values come from the TOC equivalence-class representative
    (ADR-0013); on a sibling volume whose TOC pagination differs (Centro East
    Block Vol 2 is shifted two pages, #62) the representative's page misses.
    Searching the whole TOC range anchors on where the text actually is.
    """
    toc_start, toc_end = _toc_range(conn, volume_id)
    pages = [anchor_page]
    pages.extend(p for p in range(toc_start, toc_end + 1) if p != anchor_page)
    return pages


def build_manifest(
    conn: sqlite3.Connection,
    volume_id: int,
    section_format: str = "XX XX XX",
    kinds: Iterable[str] | None = None,
) -> list[dict]:
    """Return one manifest entry per emit_markup finding for the given volume.

    `section_format` controls how section numbers appear in comment text. Use
    `detect_section_format()` against the source PDF to match the project's
    on-page style. Search terms still cover all variants for matching robustness.

    `kinds`, when given, restricts the manifest to those finding kinds.
    """
    fmt = section_format
    conn.row_factory = sqlite3.Row
    kind_list = list(kinds) if kinds is not None else None
    query = (
        "SELECT * FROM findings "
        "WHERE volume_id = ? AND expected_action = 'emit_markup' "
        "AND status IN ('candidate', 'accepted')"
    )
    params: list = [volume_id]
    if kind_list:
        placeholders = ", ".join("?" for _ in kind_list)
        query += f" AND kind IN ({placeholders})"
        params.extend(kind_list)
    query += " ORDER BY kind, section, from_section, to_section, source_page"
    rows = conn.execute(query, params).fetchall()

    toc_nums = _toc_numbers(conn, volume_id)
    toc_divisions = {n.split()[0] for n in toc_nums if n.split()}
    entries: list[dict] = []

    btnt_by_division: dict[str, list] = {}
    for r in rows:
        if r["kind"] == "body_not_in_toc":
            sec = r["section"] or ""
            parts = sec.split()
            if parts:
                btnt_by_division.setdefault(parts[0], []).append(r)
    rolled_divisions = {
        div for div, rs in btnt_by_division.items() if div not in toc_divisions
    }

    for r in rows:
        kind = r["kind"]
        subject = _SUBJECT_BY_KIND[kind]

        if kind == "broken_related_ref":
            terms = section_variants(r["to_section"])
            tags = (r["ref_class"] or "").split(",")
            suggestion = r["probable_match"]
            if "ir" in tags and suggestion:
                comment = f"IR ({format_section(suggestion, fmt)})"
            elif ("suffix" in tags or "digit_typo" in tags) and suggestion:
                comment = (
                    f"CNL section {format_section(r['to_section'], fmt)} — "
                    f"should this be {format_section(suggestion, fmt)}?"
                )
            else:
                comment = f"CNL section {format_section(r['to_section'], fmt)}"
            if "typical" in tags:
                comment += " Typical"
            entries.append({
                "kind": kind,
                "subject": subject,
                "comment": comment,
                "page": r["source_page"],
                "search_terms": terms,
                "idempotency_key": f"{subject}|{r['from_section'] or r['from_label']}->{r['to_section']}|p{r['source_page']}",
            })

        elif kind == "body_not_in_toc":
            missing = r["section"] or ""
            div = missing.split()[0] if missing.split() else ""
            if div in rolled_divisions:
                # handled in the per-division rollup pass below
                continue
            anchor = adjacent_toc_section(missing, toc_nums)
            if anchor is None:
                continue
            anchor_page = _toc_page_of(conn, volume_id, anchor) or _toc_start(conn, volume_id)
            terms = section_variants(anchor)
            comment = f"CNL section {format_section(missing, fmt)} in TOC"
            entries.append({
                "kind": kind,
                "subject": subject,
                "comment": comment,
                "page": anchor_page,
                "pages": _anchor_pages(conn, volume_id, anchor_page),
                "search_terms": terms,
                "idempotency_key": f"{subject}|{missing}|anchor:{anchor}",
            })

        elif kind == "toc_not_in_body":
            section = r["section"] or ""
            anchor_page = r["toc_page"] or _toc_start(conn, volume_id)
            terms = section_variants(section)
            comment = f"CNL section {format_section(section, fmt)} in body"
            entries.append({
                "kind": kind,
                "subject": subject,
                "comment": comment,
                "page": anchor_page,
                "pages": _anchor_pages(conn, volume_id, anchor_page),
                "search_terms": terms,
                "idempotency_key": f"{subject}|{section}|toc:{anchor_page}",
            })

        elif kind == "division_referenced_but_not_included":
            toc_start, toc_end = _toc_range(conn, volume_id)
            div = r["division"]
            anchor_terms = [f"Division {div}", f"DIVISION {div}"]
            entries.append({
                "kind": kind,
                "subject": subject,
                "comment": r["client_comment"],
                "page": toc_start,
                "pages": list(range(toc_start, toc_end + 1)),
                "search_terms": anchor_terms,
                "idempotency_key": f"{subject}|div{div}",
            })

        elif kind == "section_number_mismatch":
            body_num = r["section"] or ""
            toc_num = r["probable_match"] or ""
            basis = r["context"] or "title"
            if basis in ("suffix", "digit_typo"):
                # Near-variant numbers (#60): neither side is provably right,
                # so emit a linked two-sided AVW callout — one on the TOC
                # entry, one on the body header — instead of a correction.
                entries.append({
                    "kind": kind,
                    "subject": subject,
                    "comment": f"AVW section {format_section(body_num, fmt)}",
                    "page": r["toc_page"],
                    "search_terms": section_variants(toc_num),
                    "idempotency_key": f"{subject}|{body_num}<->{toc_num}|toc",
                })
                entries.append({
                    "kind": kind,
                    "subject": subject,
                    "comment": f"AVW TOC {format_section(toc_num, fmt)}",
                    "page": r["body_page"],
                    "search_terms": section_variants(body_num),
                    "idempotency_key": f"{subject}|{body_num}<->{toc_num}|body",
                })
            else:
                # Title match: the mis-numbered body header is the defect; the
                # correct number from the TOC is in probable_match.
                comment = (
                    f"Section number {format_section(body_num, fmt)} should be "
                    f"{format_section(toc_num, fmt)}"
                )
                entries.append({
                    "kind": kind,
                    "subject": subject,
                    "comment": comment,
                    "page": r["body_page"],
                    "search_terms": section_variants(body_num),
                    "idempotency_key": f"{subject}|{body_num}->{toc_num}",
                })

        elif kind in ("duplicate_section_number", "duplicate_section_number_and_name"):
            section = r["section"] or ""
            and_name = kind == "duplicate_section_number_and_name"
            anchor_page = r["toc_page"] or _toc_start(conn, volume_id)
            comment = (
                f"Duplicate section number{' and name' if and_name else ''} "
                f"{format_section(section, fmt)}"
            )
            entries.append({
                "kind": kind,
                "subject": subject,
                "comment": comment,
                "page": anchor_page,
                "pages": _anchor_pages(conn, volume_id, anchor_page),
                "search_terms": section_variants(section),
                "idempotency_key": f"{subject}|{section}",
            })

        elif kind in ("incomplete_placeholder", "unresolved_option_bracket"):
            # Anchor on the on-page placeholder token (stored in context); the
            # body page is the only candidate (no TOC drift to chase).
            token = r["context"] or ""
            entries.append({
                "kind": kind,
                "subject": subject,
                "comment": r["client_comment"] or "",
                "page": r["body_page"],
                "search_terms": [token] if token else [],
                "idempotency_key": f"{subject}|p{r['body_page']}|{token}",
            })

    for div in sorted(rolled_divisions):
        missing_rows = btnt_by_division[div]
        smallest = min(r["section"] for r in missing_rows if r["section"])
        anchor = adjacent_toc_section(smallest, toc_nums)
        if anchor is None:
            continue
        anchor_page = _toc_page_of(conn, volume_id, anchor) or _toc_start(conn, volume_id)
        n = len(missing_rows)
        comment = (
            f"CNL Division {div} in TOC "
            f"({n} section{'s' if n != 1 else ''} in body)"
        )
        entries.append({
            "kind": "body_division_missing_from_toc",
            "subject": _DIVISION_MISSING_SUBJECT,
            "comment": comment,
            "page": anchor_page,
            "pages": _anchor_pages(conn, volume_id, anchor_page),
            "search_terms": section_variants(anchor),
            "idempotency_key": f"{_DIVISION_MISSING_SUBJECT}|div{div}",
        })

    return entries


def emit_to_pdf(
    pdf_path: Path | str,
    manifest: list[dict],
    reviewer: str,
    output_path: Path | str | None = None,
    in_place: bool = False,
) -> EmitResult:
    """Write manifest entries as red Revu-style FreeText callouts (ADR-0012).

    Each entry becomes a borderless red-text FreeText box placed adjacent to
    the first matching search term on the entry's page (falling back through
    `pages` if provided). Existing `spec-check:`-subject annotations are
    deleted first so re-running produces no duplicates. Styling and placement
    live in `qc_core.markup`.

    Default output is `<source>.marked.pdf`; pass `in_place=True` to overwrite.
    """
    import fitz

    src = Path(pdf_path)
    out = markup.resolve_output_path(src, output_path, in_place)
    now_pdf = markup.pdf_date()
    result = EmitResult(output_path=out)
    placed_by_page: dict[int, list] = {}
    doc = fitz.open(src)
    try:
        markup.delete_markups(doc, SUBJECT_PREFIX)

        for entry in manifest:
            candidate_pages = list(entry.get("pages") or [entry["page"]])
            # Anchor pages computed from stored toc_page can drift by one
            # against the physical PDF (Centro East Block, #62): fall back to
            # the adjacent pages before declaring the entry unmatched.
            for pnum in list(candidate_pages):
                for neighbor in (int(pnum) - 1, int(pnum) + 1):
                    if neighbor not in candidate_pages:
                        candidate_pages.append(neighbor)
            anchor = None
            page = None
            for pnum in candidate_pages:
                pidx = int(pnum) - 1
                if not 0 <= pidx < doc.page_count:
                    continue
                p = doc[pidx]
                hit = markup.find_rect_on_page(p, entry.get("search_terms", []))
                if hit is not None:
                    anchor = hit
                    page = p
                    break
            if anchor is None or page is None:
                result.unmatched.append(entry)
                continue

            markup.add_freetext_markup(
                doc,
                page,
                anchor,
                comment=entry.get("comment", ""),
                reviewer=reviewer,
                subject=entry["subject"],
                now_pdf=now_pdf,
                placed_by_page=placed_by_page,
            )
            result.emitted += 1

        markup.save_doc(doc, src, out, in_place)
    finally:
        if not doc.is_closed:
            doc.close()

    return result
