"""
Spec PDF extraction — ported from legacy spec_analyzer.py into qc_core.

TOC running-header false positives (kadlec-lab expected.json suppress rows) are
filtered in is_bare_section_number and looks_like_toc_title.
"""

from __future__ import annotations

import re
from typing import Optional

try:
    import fitz  # PyMuPDF
except ImportError as exc:
    raise ImportError("PyMuPDF required. Install with: pip install pymupdf") from exc


def normalize_section_num(raw: str) -> Optional[str]:
    if not raw:
        return None
    s = raw.strip().upper()

    m = re.match(r"^\d+-(\d{6})[A-Z]?(\.\d+)?$", s)
    if m:
        digits = m.group(1)
        dec = m.group(2) or ""
        return f"{digits[:2]} {digits[2:4]} {digits[4:6]}{dec}"

    cleaned = re.sub(r"[^\d\s.]", "", s)
    no_spaces = re.sub(r"\s+", "", cleaned)

    m = re.match(r"^(\d{6})(\.\d+)?$", no_spaces)
    if m:
        d, dec = m.group(1), m.group(2) or ""
        return f"{d[:2]} {d[2:4]} {d[4:6]}{dec}"

    m = re.match(r"^(\d{8})$", no_spaces)
    if m:
        d = m.group(1)
        return f"{d[:2]} {d[2:4]} {d[4:6]}"

    parts = cleaned.strip().split()
    if len(parts) == 3 and all(re.match(r"^\d+$", p) for p in parts[:2]):
        third = parts[2]
        if re.match(r"^\d+(\.\d+)?$", third):
            return f"{parts[0].zfill(2)} {parts[1].zfill(2)} {third}"
    if len(parts) == 2 and all(re.match(r"^\d+$", p) for p in parts):
        if len(parts[1]) == 4:
            return f"{parts[0].zfill(2)} {parts[1][:2]} {parts[1][2:]}"

    return None


def is_valid_csi_number(norm: str) -> bool:
    if not norm:
        return False
    parts = norm.split()
    if not parts:
        return False
    try:
        div = int(parts[0])
        return 0 <= div <= 49
    except ValueError:
        return False


def _digit_count(raw: str) -> int:
    return sum(1 for c in raw if c.isdigit())


def looks_like_toc_title(title: str) -> bool:
    """Reject TOC running-header pairings (kadlec-lab suppress fixture)."""
    if not title or len(title.strip()) < 3:
        return False
    lower = title.lower().strip()
    if "table of contents" in lower:
        return False
    if lower in ("end of", "section", "not used", "end of section"):
        return False
    if lower.startswith("end of "):
        return False
    if re.match(r"^section\s+\d", lower):
        return False
    return True


def is_bare_section_number(line: str) -> Optional[str]:
    """
    Bare section number on its own line (two-line TOC format).
    Rejects >6 digits and lines that are TOC running headers.
    """
    stripped = line.strip()
    if not stripped:
        return None
    if "TABLE OF CONTENTS" in stripped.upper():
        return None

    s = re.sub(r"^SECTION\s+", "", stripped, flags=re.IGNORECASE).strip()

    if not re.match(r"^[\d\s.\-]{4,18}$", s):
        return None
    parts = s.split()
    if len(parts) == 3 and len(parts[1]) == 4 and parts[1].isdigit() and "." not in parts[2]:
        return None
    if "." not in s and _digit_count(s) > 6:
        return None

    norm = normalize_section_num(s)
    if norm and is_valid_csi_number(norm):
        return s
    return None


ADMIN_SECTIONS = {
    "00 00 10",
    "00 00 01",
    "00 00 05",
    "00 01 10",
    "00 01 15",
    "00 01 20",
    "00 01 25",
    "00 02 00",
    "00 02 10",
    "00 11 00",
    "00 21 00",
    "00 41 00",
    "00 45 00",
    "00 52 00",
    "00 61 00",
    "00 62 00",
    "00 70 00",
}


def is_admin(norm: str) -> bool:
    return norm in ADMIN_SECTIONS


INLINE_SECTION_RE = re.compile(
    r"(?:SECTION\s+)?(\d{1,2}[-\s.]?\d{2}[-\s.]?\d{2,4}(?:\.\d+)?|\d+-\d{6}[A-Z]?(?:\.\d+)?)",
    re.IGNORECASE,
)

TOC_HEADING_RE = re.compile(
    r"TABLE\s+OF\s+CONTENTS|SPECIFICATION\s+INDEX",
    re.IGNORECASE,
)

BODY_SECTION_HEADER_RE = re.compile(
    r"^(?:SECTION|DOCUMENT|DIVISION)\s+(\d{1,2}[-\s.]?\d{2}[-\s.]?\d{2,4}(?:\.\d+)?|\d+-\d{6}[A-Z]?(?:\.\d+)?)\s*(?:[-\u2013\u2014]\s*.+)?\s*$",
    re.IGNORECASE,
)

BODY_INDICATOR_RE = re.compile(
    r"^PART\s+1\s+GENERAL|^1\.\s*GENERAL|^PART\s+ONE",
    re.IGNORECASE,
)

DIVISION_HEADER_RE = re.compile(r"^DIVISION\s+\d+", re.IGNORECASE)

RELATED_HEADER_RE = re.compile(
    r"RELATED\s+(?:SECTIONS?|DOCUMENTS?|WORK|REQUIREMENTS?)",
    re.IGNORECASE,
)

PART_HEADER_RE = re.compile(
    r"^PART\s+\d|^PART\s+(?:ONE|TWO|THREE)|^(?:1|2|3)\.\s*GENERAL|^END\s+OF\s+SECTION",
    re.IGNORECASE,
)

CONSULTANT_RE = re.compile(
    r"\(by\s+(?:Structural|Civil|Electrical|Mechanical|Plumbing|MEP|Elevator|Specialty|"
    r"Geotechnical|Landscape|Lighting|Acoustical|Fire\s+Protection)\s+"
    r"(?:Engineer|Consultant|Designer|Contractor)\)",
    re.IGNORECASE,
)


def is_by_consultant(title: str) -> bool:
    return bool(CONSULTANT_RE.search(title))


_TOC_BOOKMARK_RE = re.compile(
    r"table\s+of\s+contents|specification\s+index", re.IGNORECASE
)
_SECTION_BOOKMARK_RE = re.compile(r"\d{2}\s*\d{2}\s*\d{2}")


def _bookmark_looks_like_toc(title: str) -> bool:
    """Recognize project-TOC bookmark titles, including numeric-prefixed
    variants (``3_TOC``) and bare ``TOC``, not just ``Table of Contents``."""
    norm = re.sub(r"^\s*\d+[_.\s)\-]+", "", title.strip()).strip()
    return norm.lower() == "toc" or bool(_TOC_BOOKMARK_RE.search(norm))


def _detect_toc_from_outline(doc) -> Optional[tuple[int, int]]:
    """Use PDF outline bookmarks as authoritative TOC range when present.

    Among bookmarks whose title looks like a TOC, prefers the shallowest
    (document-level) one and skips any nested under a spec-section bookmark —
    those are embedded sub-document TOCs (e.g. a geotechnical report's own TOC)
    rather than the project specification index. Returns (toc_start, toc_end) as
    0-based page indices: the bookmark's page through one before the next
    sibling/deeper bookmark, capped so the range is at least the TOC page itself.
    """
    try:
        outline = doc.get_toc(simple=True)
    except Exception:
        return None
    if not outline:
        return None

    n = len(doc)
    candidates: list[tuple[int, int, int]] = []  # (level, page, idx)
    ancestors: list[tuple[int, bool]] = []  # (level, is_section_bookmark)
    for idx, (level, title, page) in enumerate(outline):
        while ancestors and ancestors[-1][0] >= level:
            ancestors.pop()
        nested_under_section = any(is_section for _lvl, is_section in ancestors)
        is_section = bool(title and _SECTION_BOOKMARK_RE.search(title))
        ancestors.append((level, is_section))
        if not title or nested_under_section:
            continue
        if _bookmark_looks_like_toc(title):
            candidates.append((level, page, idx))

    if not candidates:
        return None

    candidates.sort(key=lambda c: (c[0], c[1]))
    level, page, idx = candidates[0]

    toc_page_0 = max(0, page - 1)
    next_page_0: Optional[int] = None
    for level2, _title2, page2 in outline[idx + 1 :]:
        if level2 > level:
            continue
        if page2 > page:
            next_page_0 = max(0, page2 - 1)
            break
    if next_page_0 is None:
        for _level2, _title2, page2 in outline[idx + 1 :]:
            if page2 > page:
                next_page_0 = max(0, page2 - 1)
                break
    if next_page_0 is None or next_page_0 <= toc_page_0:
        return (toc_page_0, min(toc_page_0, n - 1))
    return (toc_page_0, min(next_page_0 - 1, n - 1))


_BOOKMARK_NUMBER_RE = re.compile(r"^\s*(\d{2}[\s.]\d{2}[\s.]\d{2}(?:\.\d+)?)\s+(.*)$")


def detect_embedded_reports(doc) -> list[dict]:
    """Embedded non-CSI documents that are bound into the set (#43).

    A report like a Geotechnical Engineering Report appears in the spec TOC but
    has no ``SECTION NN NN NN`` CSI body header, so the TOC↔body diff would flag
    it as a false ``toc_not_in_body``. We recognize it from the PDF outline: a
    bookmark whose title carries a CSI number and whose subtree contains the
    document's own ``Table of Contents`` (the same nested-TOC signal #40/#41
    use to skip embedded sub-document TOCs). The bookmark's presence confirms
    the report is actually bound in.

    Returns ``[{"number", "title", "page"}]`` (1-based page) for each confirmed
    embedded report. Reports listed in the TOC but absent from the outline are
    not returned — they stay genuine "missing from set" findings.
    """
    try:
        outline = doc.get_toc(simple=True)
    except Exception:
        return []
    if not outline:
        return []

    found: dict[str, dict] = {}
    for idx, (level, title, page) in enumerate(outline):
        if not title or page <= 0:
            continue
        m = _BOOKMARK_NUMBER_RE.match(title.strip())
        if not m:
            continue
        norm = normalize_section_num(m.group(1))
        if not norm or not is_valid_csi_number(norm):
            continue
        report_title = m.group(2).strip()

        # Subtree = following entries deeper than this bookmark.
        has_nested_toc = False
        for level2, title2, _page2 in outline[idx + 1 :]:
            if level2 <= level:
                break
            if title2 and _bookmark_looks_like_toc(title2):
                has_nested_toc = True
                break
        if not has_nested_toc:
            continue
        found.setdefault(
            norm, {"number": norm, "title": report_title, "page": page}
        )

    return sorted(found.values(), key=lambda r: r["number"])


def _toc_page_density(doc, start_0: int) -> int:
    """Count section-number lines across the TOC's first few pages, used to
    sanity-check an outline-derived range against the text-scan candidate."""
    n = len(doc)
    if start_0 < 0 or start_0 >= n:
        return 0
    count = 0
    for i in range(start_0, min(start_0 + 3, n)):
        for line in doc[i].get_text().split("\n"):
            stripped = line.strip()
            if is_bare_section_number(stripped) or re.match(
                r"^\d{2}[\s.]\d{2}[\s.]\d{2}(?:\.\d+)?\s+\S", stripped
            ):
                count += 1
    return count


def detect_toc_range(doc) -> tuple[int, int, bool]:
    """Return ``(toc_start, toc_end, confirmed)`` as 0-based page indices.

    ``confirmed`` is True only when a genuine TOC was found — via a TOC outline
    bookmark or a ``TABLE OF CONTENTS`` heading page. It is False when the range
    was fabricated by the bare-section-density fallback (issue #52): a manual
    with no TOC at all otherwise gets its first body section pages crowned as a
    phantom "TOC", inverting the TOC↔body diff into ~hundreds of false findings.
    The caller skips the section-completeness check when ``confirmed`` is False.
    """
    from_outline = _detect_toc_from_outline(doc)
    # Trust the outline only when its TOC page is actually dense with section
    # numbers; a sparse range usually means we latched onto the wrong bookmark,
    # so fall back to the text scan below and compare.
    if from_outline is not None and _toc_page_density(doc, from_outline[0]) >= 5:
        return (*from_outline, True)

    n = len(doc)
    toc_start = None
    heading_confirmed = False

    for i in range(min(n, 30)):
        text = doc[i].get_text()
        if TOC_HEADING_RE.search(text):
            combined = text
            for j in range(i + 1, min(i + 3, n)):
                combined += doc[j].get_text()
            section_hits = len(INLINE_SECTION_RE.findall(combined))
            bare_nearby = sum(
                1 for line in combined.split("\n") if is_bare_section_number(line.strip())
            )
            has_divisions = bool(DIVISION_HEADER_RE.search(combined))
            is_spec_toc = (
                bare_nearby >= 2
                or section_hits >= 10
                or (has_divisions and section_hits >= 5)
            )
            if is_spec_toc:
                toc_start = i
                heading_confirmed = True
                break

    if toc_start is None:
        best_page, best_count = -1, 0
        for i in range(min(n, 40)):
            text = doc[i].get_text()
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            matches = sum(1 for line in lines if is_bare_section_number(line))
            if matches > best_count and matches >= 5:
                best_count = matches
                best_page = i
        if best_page >= 0:
            toc_start = best_page

    if toc_start is None:
        if from_outline is not None:
            # Outline failed the density gate above and no heading/text-scan
            # range was found — a sparse outline alone does not confirm (#52).
            return (*from_outline, False)
        return (0, min(9, n - 1), False)

    toc_end = toc_start
    consecutive_low = 0

    for i in range(toc_start, min(toc_start + 40, n)):
        text = doc[i].get_text()
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        if BODY_INDICATOR_RE.search(text):
            break

        all_section_refs_on_page = INLINE_SECTION_RE.findall(text)
        page_section_density = len(all_section_refs_on_page)

        is_body_section_page = False
        for j, line in enumerate(lines[:8]):
            if BODY_SECTION_HEADER_RE.match(line):
                next_lines = lines[j + 1 : j + 4] if j + 1 < len(lines) else []
                next_text = " ".join(next_lines)
                is_not_toc_heading = (
                    not TOC_HEADING_RE.search(next_text)
                    and not re.search(r"page\s+\d+\s+of\s+\d+", next_text, re.IGNORECASE)
                )
                if is_not_toc_heading and page_section_density <= 3:
                    is_body_section_page = True
                    break

        if is_body_section_page:
            break

        bare_section_count = sum(1 for line in lines if is_bare_section_number(line))
        inline_section_count = sum(
            1
            for line in lines
            if re.search(r"^\s*\d{6}\s+\S", line)
            or re.search(r"^\s*\d{2}\s+\d{2}\s+\d{2}\s+\S", line)
        )
        has_toc_heading = bool(TOC_HEADING_RE.search(text))
        has_division_header = sum(1 for line in lines if DIVISION_HEADER_RE.match(line))
        total = len(lines) if lines else 1

        is_toc_like = (
            bare_section_count >= 3
            or inline_section_count >= 3
            or has_toc_heading
            or (has_division_header >= 1 and (bare_section_count + inline_section_count) > 0)
            or (bare_section_count + inline_section_count) / total > 0.1
        )

        if is_toc_like:
            toc_end = i
            consecutive_low = 0
        else:
            consecutive_low += 1
            if consecutive_low >= 2 and i > toc_start:
                break

    # If the outline produced a range too, keep whichever first page is denser.
    if from_outline is not None and _toc_page_density(
        doc, from_outline[0]
    ) > _toc_page_density(doc, toc_start):
        return (*from_outline, heading_confirmed)
    # Only a TABLE OF CONTENTS heading page confirms here: an outline that
    # reaches this point already failed the density gate above, and the
    # bare-section-density fallback alone does not confirm (issue #52).
    confirmed = heading_confirmed
    return (toc_start, toc_end, confirmed)


def _running_header_lines(doc, toc_start: int, toc_end: int) -> set[str]:
    """Lines repeated across multiple TOC pages are running headers/footers
    (e.g. a project title block), not section entries. A real section number or
    title appears on a single page, so repetition is a reliable signal."""
    npages = toc_end - toc_start + 1
    if npages < 2:
        return set()
    pages_seen: dict[str, set[int]] = {}
    for page_idx in range(toc_start, toc_end + 1):
        for line in doc[page_idx].get_text().split("\n"):
            stripped = line.strip()
            if stripped:
                pages_seen.setdefault(stripped, set()).add(page_idx)
    threshold = max(2, (npages + 1) // 2)
    return {line for line, pages in pages_seen.items() if len(pages) >= threshold}


def extract_toc_sections(doc, toc_start: int, toc_end: int) -> list[dict]:
    # Keyed by (number, normalized-title) so a number listed twice with DISTINCT
    # titles is kept as two entries (#45), while running-header echoes / identical
    # reprints across TOC pages still collapse. Same-number/same-title dups are
    # collapsed here but still caught via the body occurrences.
    found: dict[tuple[str, str], dict] = {}
    running_headers = _running_header_lines(doc, toc_start, toc_end)

    for page_idx in range(toc_start, toc_end + 1):
        text = doc[page_idx].get_text()
        lines = text.split("\n")
        nonempty = [(i, line.strip()) for i, line in enumerate(lines) if line.strip()]

        i = 0
        while i < len(nonempty):
            _, line = nonempty[i]
            lower = line.lower()

            if line in running_headers:
                i += 1
                continue
            if TOC_HEADING_RE.search(line):
                i += 1
                continue
            if DIVISION_HEADER_RE.match(line):
                i += 1
                continue
            if lower in ("section", "not used", "end of section", "end of specifications", "contents"):
                i += 1
                continue
            if lower.startswith("toc-") or re.match(r"^toc-?\d+", lower):
                i += 1
                continue
            if re.match(r"^[.\s]+$", line) and len(line) > 5:
                i += 1
                continue

            bare = is_bare_section_number(line)
            if bare:
                norm = normalize_section_num(bare)
                if norm and is_valid_csi_number(norm):
                    title = ""
                    if i + 1 < len(nonempty):
                        _, next_line = nonempty[i + 1]
                        if (
                            not is_bare_section_number(next_line)
                            and not DIVISION_HEADER_RE.match(next_line)
                            and not re.match(r"^[.\s]+$", next_line)
                            and next_line.lower() not in ("section", "not used")
                            and len(next_line) > 1
                        ):
                            title = re.sub(r"\s*\.{2,}.*$", "", next_line)
                            title = re.sub(r"\s+\d{1,4}\s*$", "", title).strip()
                    key = (norm, normalize_title_for_dup(title))
                    if looks_like_toc_title(title) and key not in found:
                        found[key] = {
                            "number": norm,
                            "title": title,
                            "toc_page": page_idx + 1,
                        }
                i += 1
                continue

            m = INLINE_SECTION_RE.search(line)
            if m:
                raw_num = m.group(1)
                norm = normalize_section_num(raw_num)
                if norm and is_valid_csi_number(norm):
                    after = line[m.end() :].strip()
                    before = line[: m.start()].strip()
                    before = re.sub(
                        r"^(?:SECTION|SEC\.?)\s*", "", before, flags=re.IGNORECASE
                    ).strip()
                    after_clean = re.sub(r"\s*\.{2,}.*$", "", after)
                    after_clean = re.sub(r"\s+\d{1,4}\s*$", "", after_clean).strip()
                    before_clean = re.sub(r"\s*\.{2,}.*$", "", before)
                    before_clean = re.sub(r"\s+\d{1,4}\s*$", "", before_clean).strip()
                    title = (
                        after_clean
                        if len(after_clean) >= len(before_clean)
                        else before_clean
                    )
                    title = re.sub(r"\s+", " ", title).strip()
                    key = (norm, normalize_title_for_dup(title))
                    if looks_like_toc_title(title) and key not in found:
                        found[key] = {
                            "number": norm,
                            "title": title,
                            "toc_page": page_idx + 1,
                        }
            i += 1

    return _assign_occurrences(list(found.values()))


BODY_HEADER_MAX_NONEMPTY_INDEX = 30
_SENTENCE_TITLE_RE = re.compile(r"\.\s+[A-Z][a-z]")

# Running header that reliably encodes the page's true section, e.g.
# "03 20 00 - 2" (section number followed by a per-section page counter).
_RUNNING_HEADER_RE = re.compile(
    r"^(\d{2}[\s.]\d{2}[\s.]\d{2}(?:\.\d+)?)\s*[-–—]\s*(\d+)$"
)
# A real CSI body header is written all-caps ("SECTION 03 60 00 - TITLE"),
# even when the number itself is wrong (a mis-numbered header — left for #44).
# Inline prose references use title/lower case ("Section 013300 - ...").
_CAPS_SECTION_HEADER_RE = re.compile(r"^(?:SECTION|DOCUMENT|DIVISION)\s")
# Inline related-section reference: title-case "Section" + a number.
_INLINE_REF_HEADER_RE = re.compile(r"^Section\s+\d")


def _is_caps_section_header(line: str) -> bool:
    return bool(_CAPS_SECTION_HEADER_RE.match(line))


def _is_sentence_shape_title(title: str) -> bool:
    """Reject titles whose text continues into a second sentence (e.g.
    'Electrical.  Coordinate power wiring...'), which indicates the matched
    line is a sentence about a Division, not a section header."""
    return bool(_SENTENCE_TITLE_RE.search(title))


def _page_running_header_section(nonempty: list[str]) -> Optional[str]:
    """Normalized section number from the page's running header, or None.

    Real CSI body pages carry a running header like ``03 20 00 - 2`` that
    encodes the page's actual section; the section's first page reads
    ``... - 1``. We use it to reject inline ``Section NNNNNN`` prose references
    that would otherwise be mis-promoted to standalone body sections (#42)."""
    rh = _page_running_header(nonempty)
    return rh[0] if rh else None


def _page_running_header(nonempty: list[str]) -> Optional[tuple[str, int]]:
    """(normalized section, per-section page counter) from the running header,
    or None. Counter == 1 marks a section's first page — used to tell a genuine
    second section sharing a number (#45) from a continuation page."""
    for line in nonempty:
        m = _RUNNING_HEADER_RE.match(line)
        if m:
            norm = normalize_section_num(m.group(1))
            if norm and is_valid_csi_number(norm):
                return norm, int(m.group(2))
    return None


def _title_above_running_header(nonempty: list[str]) -> str:
    """Title for the sub-consultant ("by B&A") title-block layout (#58).

    These sections carry no dashed ``SECTION NN NN NN - TITLE`` header our
    regex matches; the number lives in the title-block page-number line
    (``26 05 53 - 1``, captured as the running header) with the section title
    in the ALL-CAPS line directly above it. Return that title, or "".
    """
    for i, line in enumerate(nonempty):
        m = _RUNNING_HEADER_RE.match(line)
        if not m:
            continue
        norm = normalize_section_num(m.group(1))
        if not norm or not is_valid_csi_number(norm):
            continue
        if i > 0:
            prev = nonempty[i - 1].strip()
            if prev and prev == prev.upper() and re.search(r"[A-Za-z]", prev):
                return prev
        return ""
    return ""


def normalize_title_for_dup(title: str) -> str:
    """Aggressive title normalization for duplicate-name detection (#45):
    lowercase, treat hyphen/space as equivalent, strip punctuation. So
    'Cold Formed Metal Framing' and 'Cold-Formed Metal Framing' collapse."""
    t = (title or "").lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _assign_occurrences(sections: list[dict]) -> list[dict]:
    """Number repeated section numbers 1, 2, ... in list (page) order."""
    counts: dict[str, int] = {}
    for sec in sections:
        counts[sec["number"]] = counts.get(sec["number"], 0) + 1
        sec["occurrence"] = counts[sec["number"]]
    return sections


def extract_body_sections(doc, body_start: int) -> list[dict]:
    # number -> first page seen, so a later page sharing the number is only kept
    # when the running header marks it as a genuine new section start (#45).
    first_page: dict[str, int] = {}
    occurrences: list[dict] = []
    n = len(doc)

    for page_idx in range(body_start, n):
        text = doc[page_idx].get_text()
        lines = [line.strip() for line in text.split("\n")]
        nonempty = [line for line in lines if line]

        rh = _page_running_header(nonempty)
        header_section = rh[0] if rh else None
        header_counter = rh[1] if rh else None

        found_section_this_page = False
        for line_i, line in enumerate(nonempty):
            m = BODY_SECTION_HEADER_RE.match(line)
            if not m:
                continue
            if found_section_this_page and line_i > 4:
                continue
            if line_i > BODY_HEADER_MAX_NONEMPTY_INDEX:
                continue

            raw_num = m.group(1)
            norm = normalize_section_num(raw_num)
            if not norm or not is_valid_csi_number(norm):
                continue
            if norm == "00 00 00":
                continue
            # The page's running header encodes its true section. A match whose
            # number differs AND isn't written as an all-caps "SECTION" header
            # is an inline related-section reference in body prose (e.g.
            # "Section 013300 - Submittal Procedures:" cited inside 03 20 00's
            # SUBMITTALS article), not a header (#42). All-caps headers that
            # differ are genuine mis-numbered headers, left for #44.
            if (
                header_section is not None
                and norm != header_section
                and not _is_caps_section_header(line)
            ):
                continue
            # No running header to cross-check against: reject title-case
            # "Section NNNNNN ..." prose refs (real headers are all-caps).
            if header_section is None and _INLINE_REF_HEADER_RE.match(line):
                continue
            # The number was already recorded. Only keep this as a SECOND
            # section (#45) when the page is a genuine new section start:
            # either the running header counter == 1, or (when the page carries
            # no running header) an all-caps SECTION header sits at the very top.
            # Continuation pages have counter >= 2 and no top-of-page header, so
            # they're skipped — as are mid-section self-references.
            if norm in first_page:
                on_new_page = page_idx + 1 != first_page[norm]
                # On a page with no running header, an all-caps SECTION line is
                # a genuine new start only when a PART/GENERAL indicator follows
                # shortly after (a mid-prose reference has no such structure).
                followed_by_part = any(
                    PART_HEADER_RE.match(nl) or BODY_INDICATOR_RE.search(nl)
                    for nl in nonempty[line_i + 1 : line_i + 6]
                )
                starts_section = header_counter == 1 or (
                    header_section is None
                    and _is_caps_section_header(line)
                    and followed_by_part
                )
                if not (on_new_page and starts_section):
                    found_section_this_page = True
                    continue

            dash_m = re.search(r"[-\u2013\u2014]\s*(.+)$", line.strip())
            if dash_m:
                title = dash_m.group(1).strip()
                if _is_sentence_shape_title(title):
                    continue
            else:
                title = ""
                if line_i + 1 < len(nonempty):
                    candidate = nonempty[line_i + 1]
                    if (
                        not PART_HEADER_RE.match(candidate)
                        and not BODY_SECTION_HEADER_RE.match(candidate)
                        and len(candidate) > 2
                    ):
                        title = candidate

            occurrences.append({"number": norm, "title": title, "page": page_idx + 1})
            first_page.setdefault(norm, page_idx + 1)
            found_section_this_page = True

        # Sub-consultant ("by B&A") title-block layout (#58): a genuine first
        # page (running-header counter == 1) whose section header our regex
        # never matched — the number lives only in the title-block page-number
        # line. Bind that authoritative number to the ALL-CAPS title above it.
        # Pages where a header DID match (incl. mis-numbered ones, #44) are left
        # untouched, so the typo'd 26 20 00 / .13 discrepancies still surface to
        # the reconciliation matrix for judgment rather than being silently
        # rewritten here.
        if (
            not found_section_this_page
            and header_section is not None
            and header_counter == 1
            and header_section not in first_page
        ):
            occurrences.append(
                {
                    "number": header_section,
                    "title": _title_above_running_header(nonempty),
                    "page": page_idx + 1,
                }
            )
            first_page.setdefault(header_section, page_idx + 1)

    return _assign_occurrences(occurrences)


def _build_page_label_index(doc) -> list[tuple[int, str]]:
    """Return sorted [(page_1based, label), ...] from PDF outline, excluding
    entries whose title is itself a CSI section number (those become body
    headers instead) and Table-of-Contents anchors. Used as a fallback to
    label refs whose containing section has no numeric header."""
    try:
        outline = doc.get_toc(simple=True)
    except Exception:
        return []
    out: list[tuple[int, str]] = []
    for _level, title, page in outline:
        if not title or page <= 0:
            continue
        clean = title.strip()
        norm = clean.lower()
        if norm in ("table of contents", "bookmarks", "redicheck introduction",
                    "redicheck comments"):
            continue
        # Skip pure-number bookmarks (e.g. "02 05 00") and number+title (e.g.
        # "02 32 01 Geotechnical Report") — those map to body sections.
        if re.match(r"^\d{2}\s+\d{2}\s+\d{2}", clean):
            continue
        out.append((page, clean))
    out.sort(key=lambda x: x[0])
    return out


def _label_for_page(page_label_index: list[tuple[int, str]], page_1based: int) -> Optional[str]:
    """Latest outline label whose page <= page_1based; None if outline empty
    or all entries are after this page."""
    best: Optional[str] = None
    for pg, label in page_label_index:
        if pg <= page_1based:
            best = label
        else:
            break
    return best


def extract_all_section_refs(
    doc,
    body_start: int,
    body_sections: list[dict],
    page_label_index: Optional[list[tuple[int, str]]] = None,
) -> list[dict]:
    refs = []
    n = len(doc)
    label_index = page_label_index or []

    page_to_section: dict[int, str] = {}
    for sec in body_sections:
        pg = sec["page"]
        if pg not in page_to_section:
            page_to_section[pg] = sec["number"]

    current_section = None

    for page_idx in range(body_start, n):
        text = doc[page_idx].get_text()
        lines = text.split("\n")
        page_num = page_idx + 1
        if page_num in page_to_section:
            current_section = page_to_section[page_num]

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue
            if BODY_SECTION_HEADER_RE.match(line_stripped):
                continue

            for m in re.finditer(
                r"(?:Section|Sec\.)\s+((?:\d{1,2}[-\s.]?\d{2}[-\s.]?\d{2,4}|\d+-\d{6}[A-Z]?)(?:\.\d+)?)",
                line_stripped,
                re.IGNORECASE,
            ):
                raw = m.group(1)
                norm = normalize_section_num(raw)
                if norm and is_valid_csi_number(norm) and norm != current_section:
                    from_label = (
                        _label_for_page(label_index, page_num)
                        if current_section is None
                        else None
                    )
                    refs.append(
                        {
                            "from_section": current_section,
                            "from_label": from_label,
                            "referenced_number": norm,
                            "context_line": line_stripped[:150],
                            "link_text": extract_ref_link_text(
                                line_stripped[m.end():]
                            ),
                            "page": page_num,
                        }
                    )

    return refs


# Link text trailing a cross-reference number: an optional separator then a
# title-cased phrase ("Section 05 51 13, Metal Stairs" -> "Metal Stairs").
_LINK_TEXT_RE = re.compile(
    r"""^\s*[-–—,:]?\s*["']?\s*([A-Z][A-Za-z0-9&/'()\- ]{2,60})"""
)


def extract_ref_link_text(after: str) -> Optional[str]:
    """Title text adjacent to a cross-reference (#59), or None.

    Truncates at sentence punctuation and trims dangling connectives so prose
    continuations ("Section 09 96 00 for surface preparation and...") don't
    pollute the captured title.
    """
    m = _LINK_TEXT_RE.match(after)
    if not m:
        return None
    text = re.split(r"[.;:\"]", m.group(1))[0]
    text = re.sub(r"\s+", " ", text).strip(" -–—,")
    text = re.sub(r"\s+(and|or|for|the|a|an|of|to|in|as)$", "", text, flags=re.IGNORECASE)
    if len(text) < 3 or not re.search(r"[A-Za-z]{3}", text):
        return None
    return text


# Unfinished MasterSpec boilerplate (#61). An angle-bracket editor placeholder
# (`<Insert thickness>`) is a high-precision "section is incomplete" signal. A
# choose-one option bracket (`[jurisdiction]`) is only flagged when it shares a
# line with an `<Insert ...>` — bare brackets also wrap legitimate unit
# conversions (`[0.0187 inch (0.5 mm)]`), which must not be flagged.
_INSERT_PLACEHOLDER_RE = re.compile(r"<\s*Insert\b[^>]*>", re.IGNORECASE)
_OPTION_BRACKET_RE = re.compile(r"\[[^\[\]]{1,80}\]")


def extract_placeholders(doc, body_start: int) -> list[dict]:
    """Scan body pages for incomplete-placeholder / unresolved-option residue.

    Returns ``[{"page", "kind", "token"}]`` (1-based page) in reading order.
    ``token`` is the on-page text used to anchor the callout. Option brackets
    are emitted only on lines that also carry an ``<Insert ...>`` placeholder.
    """
    out: list[dict] = []
    n = len(doc)
    for page_idx in range(body_start, n):
        page = page_idx + 1
        for line in doc[page_idx].get_text().split("\n"):
            inserts = _INSERT_PLACEHOLDER_RE.findall(line)
            for tok in inserts:
                out.append(
                    {
                        "page": page,
                        "kind": "incomplete_placeholder",
                        "token": re.sub(r"\s+", " ", tok).strip(),
                    }
                )
            if inserts:
                for m in _OPTION_BRACKET_RE.finditer(line):
                    out.append(
                        {
                            "page": page,
                            "kind": "unresolved_option_bracket",
                            "token": re.sub(r"\s+", " ", m.group(0)).strip(),
                        }
                    )
    return out


def titles_similar(t1: str, t2: str) -> bool:
    if not t1 or not t2:
        return True

    def normalize_title(t: str) -> str:
        t = t.lower()
        t = re.sub(r"[^\w\s]", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        stops = {"and", "the", "of", "for", "in", "on", "at", "to", "a", "an", "or", "by"}
        return " ".join(w for w in t.split() if w not in stops)

    n1, n2 = normalize_title(t1), normalize_title(t2)
    if n1 == n2 or n1 in n2 or n2 in n1:
        return True
    w1, w2 = set(n1.split()), set(n2.split())
    if not w1 or not w2:
        return True
    return len(w1 & w2) / len(w1 | w2) >= 0.65


def section_number_near_match(a: str, b: str) -> Optional[str]:
    """Classify two canonical CSI numbers as a near-variant pair (#60).

    'suffix'     — one is the other plus a .NN child suffix
                   (23 05 48 vs 23 05 48.13)
    'digit_typo' — same digit count, exactly one digit differs
                   (26 22 00 vs 26 20 00)
    """
    if a == b:
        return None
    base_a, _, suf_a = a.partition(".")
    base_b, _, suf_b = b.partition(".")
    if base_a == base_b:
        # same base, one bare + one suffixed -> suffix pair; two different
        # suffixes are legitimately distinct sibling sections.
        return "suffix" if bool(suf_a) != bool(suf_b) else None
    da = re.sub(r"\D", "", a)
    db = re.sub(r"\D", "", b)
    if len(da) == len(db) and sum(x != y for x, y in zip(da, db)) == 1:
        return "digit_typo"
    return None


def find_close_section_match(ref_num: str, all_known: set[str]) -> Optional[str]:
    ref_parts = ref_num.split()
    if len(ref_parts) != 3:
        return None
    for known in sorted(all_known):
        k_parts = known.split()
        if len(k_parts) != 3:
            continue
        if k_parts[:2] == ref_parts[:2] and k_parts[2] != ref_parts[2]:
            return known
    return None


def analyze_pdf(
    pdf_path: str,
    toc_start: Optional[int] = None,
    toc_end: Optional[int] = None,
) -> dict:
    """Run extraction and diff logic; returns dict compatible with legacy analyzer."""
    try:
        fitz.TOOLS.mupdf_display_errors(False)
    except Exception:
        pass

    doc = fitz.open(pdf_path)
    n = len(doc)
    auto_detected = False

    if toc_start is not None and toc_end is not None:
        toc_s = max(0, toc_start - 1)
        toc_e = min(n - 1, toc_end - 1)
        toc_confirmed = True  # caller-specified range is authoritative
    else:
        toc_s, toc_e, toc_confirmed = detect_toc_range(doc)
        auto_detected = True

    body_start = toc_e + 1
    toc_secs = extract_toc_sections(doc, toc_s, toc_e)
    body_secs = extract_body_sections(doc, body_start)
    embedded_reports = detect_embedded_reports(doc)
    page_label_index = _build_page_label_index(doc)
    related_refs = extract_all_section_refs(doc, body_start, body_secs, page_label_index)
    placeholders = extract_placeholders(doc, body_start)

    likely_scanned = False
    scan_warning = None
    if len(body_secs) == 0 and len(toc_secs) > 3:
        sample = range(body_start, min(body_start + 10, n))
        total_chars = sum(len(doc[i].get_text().strip()) for i in sample)
        avg_chars = total_chars / max(len(list(sample)), 1)
        if avg_chars < 300:
            likely_scanned = True
            scan_warning = (
                "PDF appears scanned — little extractable body text. OCR required."
            )

    doc.close()

    toc_by_num = {s["number"]: s for s in toc_secs}
    body_by_num = {s["number"]: s for s in body_secs}
    all_known = set(toc_by_num) | set(body_by_num)

    toc_nums = {num for num in toc_by_num if not is_admin(num)}
    body_nums = {num for num in body_by_num if not is_admin(num)}

    toc_only_nums = toc_nums - body_nums
    toc_not_in_body = []
    toc_by_consultant = []
    for num in sorted(toc_only_nums):
        entry = {**toc_by_num[num]}
        if is_by_consultant(entry.get("title", "")):
            toc_by_consultant.append(entry)
        else:
            toc_not_in_body.append(entry)

    body_not_in_toc = sorted(
        [body_by_num[num] for num in (body_nums - toc_nums)],
        key=lambda x: x["number"],
    )

    title_mismatches = []
    for num in sorted(toc_nums & body_nums):
        t_title = toc_by_num[num].get("title", "")
        b_title = body_by_num[num].get("title", "")
        if t_title and b_title and not titles_similar(t_title, b_title):
            title_mismatches.append(
                {
                    "number": num,
                    "toc_title": t_title,
                    "body_title": b_title,
                    "toc_page": toc_by_num[num].get("toc_page"),
                    "body_page": body_by_num[num].get("page"),
                }
            )

    broken_refs_raw = [
        r
        for r in related_refs
        if r["referenced_number"] not in all_known and not is_admin(r["referenced_number"])
    ]
    seen: set[tuple] = set()
    broken_refs = []
    for r in broken_refs_raw:
        key = (r["from_section"], r["referenced_number"])
        if key in seen:
            continue
        seen.add(key)
        broken_refs.append(r)

    return {
        "success": True,
        "meta": {
            "total_pages": n,
            "toc_range": {"start": toc_s + 1, "end": toc_e + 1},
            "body_start_page": body_start + 1,
            "auto_detected_toc": auto_detected,
            "toc_confirmed": toc_confirmed,
            "toc_section_count": len(toc_nums),
            "body_section_count": len(body_nums),
            "likely_scanned": likely_scanned,
            "scan_warning": scan_warning,
        },
        "toc_sections": sorted(toc_secs, key=lambda x: x["number"]),
        "body_sections": sorted(body_secs, key=lambda x: x["number"]),
        "embedded_reports": embedded_reports,
        "related_refs": related_refs,
        "placeholders": placeholders,
        "toc_not_in_body": sorted(toc_not_in_body, key=lambda x: x["number"]),
        "toc_by_consultant": sorted(toc_by_consultant, key=lambda x: x["number"]),
        "body_not_in_toc": body_not_in_toc,
        "title_mismatches": title_mismatches,
        "broken_related_refs": broken_refs,
    }
