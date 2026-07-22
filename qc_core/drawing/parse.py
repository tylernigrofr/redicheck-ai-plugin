"""Drawing PDF extraction — bookmarks, index page, title-block cross-check (ADR-0014)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

try:
    import fitz  # PyMuPDF
except ImportError as exc:
    raise ImportError("PyMuPDF required. Install with: pip install pymupdf") from exc

from qc_core.drawing.config import DrawingIndexConfig, TitleBlockRect

BOOKMARK_RE = re.compile(
    # Optional leading digit-led BUILDING prefix "16-" ("16-S101", "2-A101" —
    # per-building volumes whose sheets share a discipline number across
    # buildings, #86). Kept INSIDE group 1 so the parsed sheet_number stays
    # namespaced ("16-S101"): S101 in building 1 and building 16 remain distinct
    # keys. The prefix is digit-led + hyphen-glued to the letter body, so a
    # spaced "1 - COVER SHEET" (title, not a sheet) never qualifies.
    # Optional digit-led hyphen segment after the number body: "T24-1 - Title-24"
    # parses as T24-1, not a truncated T24 (#73). The (?![A-Za-z]) guard keeps
    # hyphen-glued titles intact — "A101-2ND FLOOR" still splits as A101 + title.
    # Trailing "(?:\.\d{1,2})?" keeps a `.N` sub-sheet suffix glued to the
    # number body ("A110A.1", "A140A.2" — enlarged/detail sub-sheets, #78)
    # instead of being left dangling for the title-split group to swallow.
    # Optional leading LETTER-prefix segment "(?:[A-Z]{1,4}-)?" for shared /
    # typical-detail shapes whose body is itself letter-led ("D-S201", "G-S101"
    # — detail-structural / general-structural sheets bound into building
    # volumes, #89). The full key is preserved ("D-S201") and building_prefix
    # stays NULL (the segment is letter-led, not the digit-led building
    # namespace). It only engages when a letter body follows, so digit-led
    # bodies ("E-101", "A101-2ND FLOOR", "T24-1") backtrack it to empty and are
    # unchanged; the mandatory "[\d\.]+" still rejects letter-only titles
    # ("CD-SET NOTES").
    r"^((?:\d{1,2}-)?(?:[A-Z]{1,4}-)?[A-Z]{1,4}[-\.]?[\d\.]+(?:-\d{1,3}(?![A-Za-z]))?[a-z]{0,4}(?:\.\d{1,2})?)(?:\s*[-–]\s*(.+))?",
    re.IGNORECASE,
)
# Bookmark `<NUMBER> - <TITLE>` delimiter: hyphen/en-dash with whitespace on
# BOTH sides. BOOKMARK_RE alone splits at the first hyphen, which truncates
# hyphenated sheet numbers (`T24-1 - Title-24` → `T24` / `1 - Title-24`, #74).
_BOOKMARK_DELIM_RE = re.compile(r"\s[-–]\s")
# Full-token sheet-number grammar for the bookmark number field. Same shape
# as BOOKMARK_RE's group 1 plus an optional trailing `-<digits>` segment
# (T24-1, A2.1-3) and/or a `.N` sub-sheet suffix (A110A.1, #78), anchored at
# both ends.
_BOOKMARK_SHEET_RE = re.compile(
    r"^(?:\d{1,2}-)?(?:[A-Z]{1,4}-)?[A-Z]{1,4}[-\.]?[\d\.]+(?:-\d{1,4})?[a-z]{0,4}(?:\.\d{1,2})?$",
    re.IGNORECASE,
)

# Building-prefix namespace segment ("16-S101" → "16"). Digit-led + hyphen,
# immediately followed by the letter-led discipline body (#86). Extracted as a
# parsed field so downstream consumers (#89/#90/#93) can read the namespace
# without re-parsing the key.
_BUILDING_PREFIX_RE = re.compile(r"^(\d{1,2})-(?=[A-Za-z])")


def building_prefix(sheet_number: str) -> str | None:
    """The building-namespace segment of a sheet key ("16-S101" → "16"), else None."""
    m = _BUILDING_PREFIX_RE.match(sheet_number or "")
    return m.group(1) if m else None


def _split_bookmark(text: str) -> tuple[str, str] | None:
    """Split a bookmark title into (sheet_number, title) at the ` - ` delimiter.

    Prefers the longest leading token that fully parses as a sheet number
    (rightmost viable delimiter first), so hyphenated numbers like `T24-1`
    survive titles that themselves contain ` - ` (#74). Returns None when no
    viable split exists — caller falls back to BOOKMARK_RE.
    """
    if _BOOKMARK_SHEET_RE.match(text):
        return text.upper(), ""
    for m in reversed(list(_BOOKMARK_DELIM_RE.finditer(text))):
        head = text[: m.start()].strip()
        if _BOOKMARK_SHEET_RE.match(head):
            return head.upper(), text[m.end() :].strip()
    return None
INDEX_PAGE_RE = re.compile(
    # Umbrella forms plus discipline-prefixed forms ("CIVIL INDEX", "LANDSCAPE INDEX",
    # "FRONT END INDEX", "ARCHITECTURAL SITE INDEX"). Some firms — including the one
    # behind the Juvenile fixture — stack multiple per-discipline index sections on a
    # single title sheet rather than carrying a single umbrella "SHEET INDEX" table.
    # See ADR-0014.
    r"\b("
    r"SHEET\s+INDEX|DRAWING\s+INDEX|INDEX\s+OF\s+(DRAWINGS|SHEETS)|"
    r"SHEET\s+LIST|LIST\s+OF\s+DRAWINGS"
    r"|[A-Z][A-Z\s/&]{1,40}?\s+INDEX"
    r")\b",
    re.IGNORECASE,
)
SHEET_TOKEN_RE = re.compile(
    r"\b("
    r"[A-Z]{1,4}-\d+(?:\.\d+)?[a-zA-Z]?|"
    r"[A-Z]{1,4}\d{2,4}[a-zA-Z]?|"
    r"M-\d{3}|P-\d{3}|E-\d{3}|"
    r"[A-Z]{2,4}\d+\.\d+[a-zA-Z]?"
    r")\b",
    re.IGNORECASE,
)
# Discipline prefix, skipping an optional building-namespace segment so
# "16-S101" and normalized "16S101" both yield discipline prefix "S" (#86).
# The hyphen is optional to cover normalize_sheet_number output, which collapses
# it. Non-prefixed keys ("S101") are unaffected — the digit group is optional
# and sheet numbers are always letter-led once the building segment is stripped.
_SHEET_PREFIX_RE = re.compile(r"^(?:\d{1,2}-?)?([A-Z]{1,4})")

# Bookmarks and raw index text produced by some firms include a space between
# the discipline prefix and the sheet number — e.g. "E. 000", "EP. 100",
# "EX. A".  Collapse these before applying any sheet-number grammar so both
# channels agree.  The pattern requires an alphanumeric character after the
# space so that a bare "E. -" (no number) is never silently accepted.
_PREFIX_SPACE_RE = re.compile(r"^([A-Z]{1,4}\.)\s+([A-Za-z0-9])", re.IGNORECASE)


def _normalize_prefix_space(text: str) -> str:
    """Collapse 'E. 000' → 'E.000', 'EP. 100' → 'EP.100', 'EX. A' → 'EX.A'."""
    return _PREFIX_SPACE_RE.sub(r"\1\2", text, count=1)


def normalize_sheet_number(raw: str) -> str:
    """Comparison key — collapse whitespace and hyphens (legacy compare_with_index)."""
    return re.sub(r"[\s\-]+", "", raw.strip().upper())


def _normalize_title_for_dup_compare(title: str) -> str:
    """Forgiving title comparison for #76 duplicate detection — strip, casefold,
    collapse whitespace so trivial formatting differences don't mask a
    genuinely-identical (noise) title as a real duplicate pair."""
    return re.sub(r"\s+", " ", (title or "").strip().casefold())


def _is_plausible_sheet_token(token: str) -> bool:
    sn = token.strip().upper()
    if len(sn) < 2 or len(sn) > 20:
        return False
    if sn in ("OF", "BOX", "P.O", "PO"):
        return False
    if re.match(r"^U\d{3}$", sn):
        return True
    if not re.search(r"\d", sn):
        return False
    if sn.count(".") > 2:
        return False
    # Allow an optional digit-led building-prefix segment ("1-S101", "16-M101")
    # before the letter-led body (#88); non-prefixed keys are unaffected.
    return bool(re.match(r"^(?:\d{1,2}-)?[A-Z]", sn))


def extract_bookmarks(
    doc: fitz.Document,
) -> tuple[list[dict], float, list[dict]]:
    """Depth-2 TOC entries as sheet catalog (method A).

    Returns (parsed, parse_rate, anomalies).  Anomalies are depth-2 entries
    that fail to produce a grammar-valid sheet number after normalization —
    they are emitted as parse_anomaly findings (ADR-0027 / issue #65).
    parse_rate is derived from countable rows: len(parsed) / depth2.
    """
    depth2 = 0
    parsed: list[dict] = []
    anomalies: list[dict] = []
    for level, title, page in doc.get_toc():
        if level != 2:
            continue
        depth2 += 1
        raw_title = title.strip()
        normalized = _normalize_prefix_space(raw_title)
        # Delimiter-aware split first (#74): ` - ` with surrounding whitespace,
        # longest grammar-valid leading token wins. BOOKMARK_RE remains the
        # fallback for entries without a spaced delimiter ("A101- PLAN").
        split = _split_bookmark(normalized)
        if split is None:
            m = BOOKMARK_RE.match(normalized)
            if not m:
                anomalies.append(
                    {
                        "raw": raw_title,
                        "page": int(page),
                        "reason": "bookmark_re_no_match",
                    }
                )
                continue
            split = (m.group(1).upper(), (m.group(2) or "").strip())
        parsed.append(
            {
                "sheet_number": split[0],
                "title": split[1],
                "page": int(page),
                "confidence": "high",
                "building_prefix": building_prefix(split[0]),
            }
        )
    rate = (len(parsed) / depth2) if depth2 else 0.0
    return parsed, rate, anomalies


_LETTERSPACE_RE = re.compile(r"(?<=\b[A-Za-z]) (?=[A-Za-z]\b)")


def _collapse_letterspacing(text: str) -> str:
    """Collapse single spaces between single letters so header detection survives
    letter-spaced title typography (e.g. ``S H E E T  I N D E X`` → ``SHEET  INDEX``).

    Only intra-word single-glyph spacing is removed; the double space between
    words is left intact, so ``SHEET\\s+INDEX``-style patterns still match.
    """
    prev = None
    out = text
    # Apply repeatedly: collapsing one gap can expose the next (S·H·E·E·T).
    while out != prev:
        prev = out
        out = _LETTERSPACE_RE.sub("", out)
    return out


# Fallback index-header form (#54): SMHa heads its master-index table
# "BUILDING DRAWINGS" with no INDEX word anywhere on the page (Azalea Phase 4
# main and "- Shed" volumes). Consulted only when no page matches the primary
# patterns, so it can never redirect an existing detection.
INDEX_PAGE_FALLBACK_RE = re.compile(r"\bBUILDING\s+DRAWINGS\b", re.IGNORECASE)


# Extraction-blindness heuristic (issue #75). A page yielding fewer vector-text
# chars than the floor is treated as raster/flattened (the residual chars are
# typically a prior markup pass's stamp text — 1300 W 218th Landscape pages
# yield exactly 95 chars each). A volume is suspected raster when either the
# majority of its pages are below the floor, or an index header was found on a
# page from which zero index rows parsed (header band vector, listing raster —
# 1300 W 218th Electrical p.2: 796 chars total, "ELECTRICAL SHEET INDEX"
# present, zero rows).
RASTER_CHAR_FLOOR = 150
RASTER_PAGE_FRACTION = 0.5
# A vector index *listing* yields thousands of chars (real index pages in the
# calibration sets run 1,500-25,000+). A page carrying an index header but
# under this floor holds at most a header band of vector text — the table
# itself is flattened. Electrical p.2 of 1300 W 218th: 796 chars.
INDEX_PAGE_CHAR_FLOOR = 1000


def compute_extraction_signal(
    page_char_counts: list[int],
    index_header_page: int | None,
    index_rows_parsed: int,
) -> dict:
    """Per-volume extraction-blindness signal (issue #75).

    ``index_rows_parsed`` counts index entries that SURVIVED the coverage
    gate in analyze_pdf (a raster header page can still scrape 1-2 junk
    rows; what matters is that nothing usable came out).

    Recorded at index time in drawing_volumes.extraction_signal and consulted
    by evaluate_invariants so a raster/flattened index trips `index_unreadable`
    instead of the semantically wrong `prefix_absent_from_index`.
    """
    raster_pages = [
        i + 1 for i, n in enumerate(page_char_counts) if n < RASTER_CHAR_FLOOR
    ]
    total = len(page_char_counts)
    fraction = (len(raster_pages) / total) if total else 0.0
    header_page_chars = (
        page_char_counts[index_header_page - 1]
        if index_header_page is not None and 0 < index_header_page <= total
        else None
    )
    # Header-without-rows: an index header detected on a text-thin page from
    # which no usable rows parsed. The thinness floor keeps vector pages whose
    # parse was rejected for other reasons (finish-schedule false positives)
    # from masquerading as raster.
    header_without_rows = (
        index_header_page is not None
        and index_rows_parsed == 0
        and header_page_chars is not None
        and header_page_chars < INDEX_PAGE_CHAR_FLOOR
    )
    suspected = header_without_rows or (
        total >= 2 and fraction >= RASTER_PAGE_FRACTION
    )
    return {
        "page_char_counts": page_char_counts,
        "index_header_page": index_header_page,
        "index_rows_parsed": index_rows_parsed,
        "header_page_chars": header_page_chars,
        "header_without_rows": header_without_rows,
        "raster_pages": raster_pages,
        "raster_page_fraction": round(fraction, 3),
        "suspected_raster": suspected,
    }


def find_index_page(doc: fitz.Document, *, max_pages: int = 15) -> Optional[int]:
    """1-based page number with index header, or None (method B).

    Kept for backwards compatibility with callers that need only the first hit.
    For multi-discipline volumes use find_all_index_pages instead.
    """
    for i in range(min(max_pages, doc.page_count)):
        txt = doc[i].get_text("text") or ""
        if INDEX_PAGE_RE.search(txt) or INDEX_PAGE_RE.search(_collapse_letterspacing(txt)):
            return i + 1
    for i in range(min(max_pages, doc.page_count)):
        txt = doc[i].get_text("text") or ""
        if INDEX_PAGE_FALLBACK_RE.search(txt):
            return i + 1
    return None


def _extract_all_page_text(doc: fitz.Document) -> list[str]:
    """One vector-text extraction per page, shared by every downstream consumer.

    `get_text` on dense drawing sheets dominates indexing runtime; the header
    scan (#71), the raster char counts (#75), and the continuation/parse walk
    must all read from this single pass instead of re-extracting.
    """
    return [doc[i].get_text("text") or "" for i in range(doc.page_count)]


def find_all_index_pages(
    doc: fitz.Document, *, page_texts: list[str] | None = None
) -> list[int]:
    """Return all 1-based page numbers that carry an index header, whole-volume scan.

    Includes fallback patterns. Duplicate pages are de-duped preserving order.
    """
    texts = page_texts if page_texts is not None else _extract_all_page_text(doc)
    result: list[int] = []
    for i, txt in enumerate(texts):
        collapsed = _collapse_letterspacing(txt)
        if (
            INDEX_PAGE_RE.search(txt)
            or INDEX_PAGE_RE.search(collapsed)
            or INDEX_PAGE_FALLBACK_RE.search(txt)
        ):
            result.append(i + 1)
    return result


# Sheet-number grammar, shared by the bare (own-line) and inline (number + title
# on one line) matchers. Two top-level forms:
#   1. prefix + digits, then either up to 4 trailing letters (A101A) OR a
#      dot-suffix that is digit-led (.06A, .2A, .4) or 1-2 letters (.A, .EC),
#      optionally followed by a second dot-segment for three-part numbers.
#      The second segment may be digits (Q0.2.1 campus-fiber sub-sheets) OR
#      1-2 letters (SA1.12.S / SA1.11.F structural slab variants — Atlas, #39).
#   2. prefix + dot + digits[+letters] with NO digit before the dot
#      (ID.000, ID.400A, G.10, EN.1, GRN.1, T.01, ABS.11 — the specialty
#      discipline sections of Atlas's master index, #39).
# Trailing letters and dot-suffixes stay mutually exclusive so a code like
# FR5210.ECD still can't parse (see #23): form 1 rejects the 3-letter suffix,
# and form 2 requires the prefix to butt straight against the dot.
_SHEET_CORE = (
    # Optional leading digit-led BUILDING prefix ("1-", "16-") and/or letter-led
    # detail/shared prefix ("D-", "G-"), mirroring BOOKMARK_RE (#86 commit
    # 7d88c3b, #89 commit a3866de). The index-page TEXT grammar never got these
    # (they landed on the bookmark grammar only), so building-namespaced index
    # rows ("1-G000", "16-S101", "D-S201") parsed to zero across the whole
    # Valrico set (#88/#93). Both segments are optional and the body stays
    # letter-led, so a digit-led body ("E-101", "E-1-01", "T24-1") backtracks
    # the letter-prefix to empty and non-prefixed keys ("S101") are unchanged.
    r"(?:\d{1,2}-)?(?:[A-Z]{1,4}-)?"
    r"(?:"
    r"[A-Z]{1,4}-?\d{1,4}(?:[A-Za-z]{0,4}|\.(?:\d[A-Za-z0-9]{0,3}|[A-Za-z]{1,2})(?:\.(?:\d{1,3}|[A-Za-z]{1,2}))?)"
    r"|[A-Z]{1,4}\.\d{1,4}[A-Za-z]{0,3}"
    # 3. prefix + digits + hyphen + digits (T24-1..T24-6 — Stockton's Title-24
    #    compliance sheets, #73). The hyphen segment is digit-led so prose
    #    fragments like "TITLE-A" can't qualify, and the prefix-digit body
    #    keeps single-letter occupancy codes (R-2, S-2) in form 1's territory.
    r"|[A-Z]{1,4}\d{1,4}-\d{1,3}[A-Za-z]?"
    # 4. prefix-hyphen-digits-hyphen-digits (E-1-01, G-0-01, P-2-03 — Quarry
    #    Oaks's discipline-building-sequence numbering). Mirrors the bookmark
    #    channel's optional trailing -<digits> segment (#74) so both channels
    #    agree on these keys. The building segment is a single digit and the
    #    sequence 2-3 digits (E-1-01, P-1-100), so project numbers like
    #    Lakeshore's "A-22-007" title-block UWSA number (two-digit year first
    #    segment) can't qualify, and bare R-2 occupancy codes stay in form 1's
    #    territory.
    r"|[A-Z]{1,4}-\d-\d{2,3}[A-Za-z]?"
    r")"
)
_LINE_SHEET_RE = re.compile(r"^" + _SHEET_CORE + r"$")
# Inline row: ``SA1.12.1 BLDG A -2ND STORY SLAB PLAN`` — sheet number and title
# share one line (some firms lay out the master index this way). The title must
# carry at least one letter so date / issuance fragments don't qualify.
#
# Inline matching is restricted (see _inline_row): a token qualifies only if it
# has a multi-letter discipline prefix (EBM2.1, SA1.12.1) OR carries two dots
# (SA1.12.S). Single-letter-prefix shallow tokens are left to the bare own-line
# path only — schedules and legends list short codes like ``A1 STANDARD KING
# STUDIO`` / ``A2.1 …`` (Embassy unit types) inline, and admitting those would
# flood `sheet_in_index_not_in_set`. Real inline sheet rows never look that thin.
_INLINE_SHEET_RE = re.compile(r"^(" + _SHEET_CORE + r")\s+(.*[A-Za-z].*)$")


def _inline_row(line: str):
    """Return (token, title) for a qualifying inline sheet row, else None."""
    m = _INLINE_SHEET_RE.match(line)
    if not m:
        return None
    token = m.group(1).upper()
    # A building-namespaced token ("1-M151") is strong evidence of a real sheet,
    # not a unit-type legend ("A1 STANDARD KING STUDIO"), so it bypasses the
    # shallow single-letter-prefix guard even though its discipline letter is
    # length-1 (#88).
    if building_prefix(token):
        return token, m.group(2).strip()
    pm = _SHEET_PREFIX_RE.match(token)
    prefix = pm.group(1) if pm else ""
    if len(prefix) < 2 and token.count(".") < 2:
        return None
    return token, m.group(2).strip()


# Date token glued to the front of an index row (#53): every Azalea discipline
# used `MM.DD.YY` on its own line, but Citadel's Structural rows arrived as
# `2026-05-27 S4.1 STATION PARKING…` — date and sheet row on ONE line, so
# neither the bare nor the inline regex matched and the whole group vanished.
_LEADING_DATE_RE = re.compile(
    r"^(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s+"
)


def _normalize_date_row(ln: str) -> list[str]:
    """Expand a date-prefixed sheet row into clean line(s); else pass through.

    Issuance lines like ``05.28.26 ISSUED FOR PERMIT`` must stay intact so the
    existing date/issuance skip in `_parse_index_lines` still rejects them.
    Date-prefixed inline rows are split into a bare token line + title line:
    the date prefix marks a real index row, so the shallow-inline-token guard
    in `_inline_row` (which would reject e.g. `S4.1`) must not apply here.
    """
    m = _LEADING_DATE_RE.match(ln)
    if not m:
        return [ln]
    rest = ln[m.end() :]
    if _LINE_SHEET_RE.match(rest):
        return [rest]
    im = _INLINE_SHEET_RE.match(rest)
    if im:
        return [im.group(1), im.group(2).strip()]
    return [ln]


# Near-miss index line: a leading token that looks sheet-number-shaped
# (1-4 letter prefix immediately followed by a digit, total ≤ 10 chars, no
# hyphens in mid-token) but fails strict _SHEET_CORE, followed by a clearly
# title-like remainder (at least two words starting with an uppercase letter).
# This tight structure keeps out material codes (TR-CL-16), fire-rating
# standards (EN13501 - 1:CFL), and product numbers (B-35883, AOS130A4GM30K4).
# Groups: (1) leading token, (2) remainder.
_INDEX_NEAR_MISS_RE = re.compile(
    r"^([A-Za-z]{1,4}\d[A-Za-z0-9.]{0,6})\s+([A-Z].{3,})$"
)


def extract_index_anomalies(lines: list[str]) -> list[dict]:
    """Near-miss lines from an index page that failed _SHEET_CORE but look sheet-shaped.

    A line qualifies as a near-miss when ALL of the following hold:
    - _LINE_SHEET_RE rejected the line (strict grammar missed it)
    - _inline_row also rejected it
    - Leading token: 1-4 letters immediately followed by a digit (no leading
      hyphen/dot), then up to 6 more alphanumeric/dot chars — total token
      ≤ 10 chars — and token itself fails _LINE_SHEET_RE
    - Remainder: starts uppercase, at least two words, no code-shaped
      fragments at the front (colon-separated, dash-digit sequences)
    - Line is not too long (prose) and remainder is not a date

    Calibrated to produce zero anomalies on Quarry Oaks and Embassy Clearwater
    fixture index pages (legends, dates, product codes, abbreviations excluded).
    """
    anomalies: list[dict] = []
    for ln in lines:
        ln_stripped = ln.strip()
        if not ln_stripped:
            continue
        if _LINE_SHEET_RE.match(ln_stripped):
            continue
        if _inline_row(ln_stripped):
            continue
        m = _INDEX_NEAR_MISS_RE.match(ln_stripped)
        if not m:
            continue
        token = m.group(1)
        remainder = m.group(2)
        # Token itself must fail _LINE_SHEET_RE; if valid, _inline_row excluded
        # it for good reason (shallow single-prefix guard on inline rows).
        if _LINE_SHEET_RE.match(token.upper()):
            continue
        # Remainder: at least two whitespace-separated words (title, not a code).
        if len(remainder.split()) < 2:
            continue
        # Exclude code-like remainders: starts with digit, dash-digit, or has
        # colon-separated fragments right after the token (fire-rating codes etc).
        if re.match(r"^[\d\-]|\d:\w", remainder):
            continue
        # Exclude date-led remainders.
        if re.match(r"^\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}", remainder):
            continue
        # Exclude long prose lines.
        if len(ln_stripped) > 100:
            continue
        anomalies.append({"raw": ln_stripped, "token": token, "remainder": remainder})
    return anomalies


def _parse_index_lines(
    lines: list[str], *, return_dup_counts: bool = False
) -> list[dict] | tuple[list[dict], dict[str, int]]:
    """Walk lines, emit one entry per `SheetNum → Title` pair.

    Index tables list `SheetNum / Title / [issuance / date]` per row. A real
    entry is a sheet-shaped line whose immediate successor is a non-sheet,
    non-digit-leading line shorter than 100 chars (the title). Tokens that
    appear in title blocks / project directories typically lack that follower
    or are followed by another sheet-shaped token, so this filter drops most
    of the token-scrape noise (e.g. abbreviation codes on legend pages).
    Multi-line titles are accepted by greedy-extending to the next sheet line.

    ``return_dup_counts=True`` additionally returns a ``{sheet_number: count}``
    dict of keys repeated MORE THAN ONCE within these same lines (one page's
    worth of index text) — a real intra-region duplicate row (#76), distinct
    from a token merely re-dedupe'd across pages/regions elsewhere. Legend
    entries poisoning ``seen`` (DENOTES rows) are not counted as duplicates.
    """
    # Normalize prefix-space forms ("E. 202" → "E.202") and strip trailing dots
    # ("M203." → "M203") before any sheet-number grammar is applied.  Both are
    # typographic quirks that appear in raw PDF text from some firms.
    def _clean_index_line(s: str) -> str:
        s = _normalize_prefix_space(s)
        # Trailing dot only: strip when the result still looks sheet-shaped.
        if s.endswith(".") and not s.endswith(".."):
            candidate = s[:-1]
            if _LINE_SHEET_RE.match(candidate):
                return candidate
        return s

    # A real intra-table duplicate row sits immediately (or near-immediately)
    # next to its twin, WITH A DIFFERENT TITLE each time (two distinct index
    # entries mistakenly sharing one sheet number — Artisan Prescot's civil
    # index: bare NCG01 twice, "Ground Stabilization..." then "Self
    # Inspection..."). Detail-callout noise (a reference bubble sitting next
    # to a blank "______" field, repeated many times close together —
    # Juvenile Correctional's Architectural volume) produces the SAME token
    # repeatedly too, but either with no title or the identical title
    # bleeding through from nearby real content each time — never two
    # genuinely different titles. Only the differing-title shape is trusted;
    # detection is restricted to the titled-row path (inline/number-only
    # rows lack a strong enough title signal to safely compare).
    _DUP_PROXIMITY_WINDOW = 2

    lines = [_clean_index_line(out) for ln in lines for out in _normalize_date_row(ln)]
    entries: list[dict] = []
    seen: set[str] = set()
    poisoned: set[str] = set()  # DENOTES-legend tokens — not real duplicates
    last_line: dict[str, int] = {}
    first_title: dict[str, str] = {}
    dup_counts: dict[str, int] = {}
    i = 0
    while i < len(lines):
        ln = lines[i]
        if not _LINE_SHEET_RE.match(ln):
            # Inline layout: number and title on the same line. Only consult this
            # after the bare match fails (the two are mutually exclusive — the
            # bare regex is anchored, so a line with a trailing title never
            # matches it).
            inline = _inline_row(ln)
            if inline:
                token, title = inline
                if (
                    _is_plausible_sheet_token(token)
                    and not re.match(r"^\d{1,4}[\-/\.]\d", title)
                    and not re.match(r"^DENOTES\b", title, re.IGNORECASE)
                    and token not in seen
                ):
                    seen.add(token)
                    entries.append({"sheet_number": token, "title": title})
            i += 1
            continue
        token = ln.upper()
        if not _is_plausible_sheet_token(token):
            i += 1
            continue
        # Look ahead for a title line.
        title_parts: list[str] = []
        j = i + 1
        while j < len(lines) and j < i + 3:
            nxt = lines[j]
            if _LINE_SHEET_RE.match(nxt) or _inline_row(nxt):
                break
            # Skip date / issuance rows but keep titles that start with a digit
            # (e.g. "1ST FLOOR PLAN", "2ND FLOOR DEMO", "3 BEDROOM UNIT").
            if re.match(r"^\d{1,4}[\-/\.]\d", nxt) or re.match(
                r"^\d{4}\s*$", nxt
            ):
                break
            if len(nxt) >= 100:
                break
            title_parts.append(nxt)
            j += 1
            # Accept at most 2 title-continuation lines.
            if len(title_parts) >= 2:
                break
        if not title_parts:
            # Number-only row (#73): multi-column index tables emit text in
            # column order, so runs of bare sheet numbers arrive with no
            # adjacent title ("M103 / M104 / M101 / MECHANICAL 1ST STORY…").
            # Accept the bare token — reconciliation keys on the number, not
            # the title. Title stays "" so downstream substantive-title
            # filters (continuation walk) ignore these rows.
            if token not in seen:
                seen.add(token)
                first_title[token] = ""
                entries.append({"sheet_number": token, "title": ""})
            i += 1
            continue
        # Drop symbol-legend entries — labels like "DENOTES SECTION LETTER"
        # appear alongside sheet-shaped tokens (e.g. "S1.0") on some index
        # pages as part of a symbols legend, not as real sheet entries.
        # Also poison `seen` so later occurrences of the same token on the
        # same legend (with a different annotation) get suppressed too.
        if re.match(r"^\s*DENOTES\b", title_parts[0], re.IGNORECASE):
            seen.add(token)
            poisoned.add(token)
            i = j
            continue
        title = " ".join(title_parts).strip()
        if token in seen:
            prior_title = first_title.get(token, "")
            # Substantive-title bar (same threshold as _find_continuation_pages'
            # own noise filter): "3H" / "1E" / "OPP" / "SIM" detail-callout
            # tokens on a plan/detail sheet swept into the continuation walk
            # are short and differ from each other by construction (every
            # callout is a different reference) — that's noise masquerading
            # as the differing-title signal, not a real duplicate row.
            if (
                token not in poisoned
                and i - last_line.get(token, i) <= _DUP_PROXIMITY_WINDOW
                and len(title) >= 10
                and len(prior_title) >= 10
                and _normalize_title_for_dup_compare(title)
                != _normalize_title_for_dup_compare(prior_title)
            ):
                # A real repeated row in the SAME index table (#76) — a sheet
                # number listed twice, close by, with a genuinely DIFFERENT
                # title each time (not a callout-noise bleed of the same
                # nearby title).
                dup_counts[token] = dup_counts.get(token, 1) + 1
                last_line[token] = i
            i = j
            continue
        seen.add(token)
        last_line[token] = i
        first_title[token] = title
        entries.append({"sheet_number": token, "title": title})
        i = j

    if return_dup_counts:
        return entries, {k: v for k, v in dup_counts.items() if v > 1}
    return entries


def _find_continuation_pages(
    doc: fitz.Document,
    start_page: int,
    *,
    max_extra: int = 10,
    project_bookmark_prefixes: set[str] | None = None,
    page_texts: list[str] | None = None,
) -> list[int]:
    """1-based pages, starting from `start_page`, that look like index continuations.

    Continuation = page yields >= 5 paired entries via `_parse_index_lines`. Stops
    at the first page that fails the threshold. Returns at least `[start_page]`
    even if it parses poorly, so analyse_pdf can attribute the source.

    When project-wide bookmark prefixes are supplied, the >= 5 threshold counts
    only entries whose prefix corresponds to a real sheet somewhere in the
    project (#23). A genuine index continuation lists real project sheet numbers;
    the schedule/finish sheets that *follow* an index page (QO Interior Design
    pages 3-10: hardware/finish/material schedules) carry one cover-sheet number
    each in their title block plus a flood of schedule codes (HD-/FT-/DF-/PF-/...)
    that look sheet-shaped but match no project prefix. Filtering by project
    prefix collapses each such page to ~1 qualifying entry, so the walk stops at
    the real index page instead of scraping the schedule bodies.
    """
    pages = [start_page]
    for i in range(start_page, min(start_page + max_extra, doc.page_count)):
        txt = (
            page_texts[i]
            if page_texts is not None
            else (doc[i].get_text("text") or "")
        )
        lines = [ln.strip() for ln in txt.split("\n") if ln.strip()]
        rows = _parse_index_lines(lines)
        # Continuation pages have many entries whose titles are real prose, not
        # the underscores / single-token detail callouts that appear on actual
        # drawing sheets (e.g. Juvenile Vol 3 pages 3-12 produce 7-17 "paired"
        # entries because A530/A540/A609 detail refs sit next to "______" labels).
        substantive = [
            r for r in rows
            if r.get("title") and len(r["title"]) >= 10 and not r["title"].strip("_").strip() == ""
        ]
        if project_bookmark_prefixes is not None:
            substantive = [
                r for r in substantive
                if (m := _SHEET_PREFIX_RE.match(r["sheet_number"]))
                and m.group(1).upper() in project_bookmark_prefixes
            ]
        if len(substantive) >= 5:
            pages.append(i + 1)
        else:
            break
    return pages


def parse_index_page_text(text: str) -> list[dict]:
    """Sheet numbers listed on a Sheet Index page (column-aware)."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    return sorted(_parse_index_lines(lines), key=lambda e: e["sheet_number"])


def parse_index_page_duplicates(text: str) -> dict[str, int]:
    """Sheet numbers listed MORE THAN ONCE on this same index page (#76).

    A real intra-region duplicate row (e.g. a bare key listed twice in one
    civil index table) — distinct from cross-page/cross-region dedup, which
    is normal (continuation overlap, master+volume index both listing a key).
    """
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    _, dup_counts = _parse_index_lines(lines, return_dup_counts=True)
    return dup_counts


def _title_block_text(page: fitz.Page, rect: TitleBlockRect) -> str:
    w, h = page.rect.width, page.rect.height
    clip_br = fitz.Rect(w * rect.x0, h * rect.y0, w * rect.x1, h * rect.y1)
    clip_bottom = fitz.Rect(0, h * rect.bottom_strip_y0, w, h)
    return (page.get_textbox(clip_br) or "") + " " + (page.get_textbox(clip_bottom) or "")


def titleblock_crosscheck(
    doc: fitz.Document,
    sheets: list[dict],
    rect: TitleBlockRect,
    *,
    sample: int = 20,
) -> list[dict]:
    """Pages where bookmark sheet number is absent from title-block text."""
    mismatches: list[dict] = []
    for entry in sheets[:sample]:
        page_idx = entry["page"] - 1
        if page_idx < 0 or page_idx >= doc.page_count:
            continue
        combined = _title_block_text(doc[page_idx], rect)
        if entry["sheet_number"] not in combined and normalize_sheet_number(
            entry["sheet_number"]
        ) not in normalize_sheet_number(combined):
            mismatches.append(
                {
                    "sheet_number": entry["sheet_number"],
                    "page": entry["page"],
                    "title": entry.get("title"),
                }
            )
    return mismatches


def _prefixes(sheet_numbers) -> set[str]:
    out: set[str] = set()
    for sn in sheet_numbers:
        m = _SHEET_PREFIX_RE.match(sn)
        if m:
            out.add(m.group(1).upper())
    return out


def classify_index_scope(
    sheets: list[dict],
    index_rows: list[dict],
    *,
    project_bookmark_prefixes: set[str] | None = None,
    project_sheet_keys: set[str] | None = None,
) -> str:
    """Content-driven master/volume classification (ADR-0014).

    A PDF's index is "master" when it both (a) substantially covers its own
    volume's sheets and (b) lists a meaningful number of entries with prefixes
    outside this volume's bookmarks — i.e. it references other volumes. Otherwise
    its scope is just this volume.

    Thresholds tuned empirically on Quarry Oaks + Juvenile fixtures: master
    requires own >= 10 AND at least 2 distinct outside-prefixes each with >= 10
    entries. This distinguishes a real cross-volume master (QO "01 General" lists
    S×64, L×39, ID×37, ... outside-prefixes) from per-volume indexes whose token
    scrape picks up legend/abbreviation codes that happen to look sheet-shaped
    (QO Civil yields outside-prefixes like ST×11, LS×7, DT×6, AR×5; Juvenile
    Vol 1 yields CW×11, HMM×8, DHM×4 — each with at most one prefix crossing 10).
    Filename heuristics (matching "General") misclassify multi-volume sets like
    Juvenile where every volume's title sheet carries a discipline-prefixed
    index that only lists that volume's sheets.
    """
    if not index_rows:
        return "volume_index"
    bookmark_prefixes = _prefixes(s["sheet_number"] for s in sheets)
    if not bookmark_prefixes:
        return "volume_index"
    own = 0
    outside_counts: dict[str, int] = {}
    for row in index_rows:
        m = _SHEET_PREFIX_RE.match(row["sheet_number"])
        if not m:
            continue
        prefix = m.group(1).upper()
        if prefix in bookmark_prefixes:
            own += 1
        else:
            # When project-wide context is provided, only count outside prefixes
            # that correspond to real sheets in OTHER PDFs of the project — this
            # filters finish/hardware/material schedule codes that look
            # sheet-shaped but aren't cross-volume references (e.g. QO Interior
            # Design's cover sheet lists DF/HD/PF finish codes; without the
            # project filter the classifier falsely promotes ID to master).
            if project_bookmark_prefixes is not None and prefix not in project_bookmark_prefixes:
                continue
            outside_counts[prefix] = outside_counts.get(prefix, 0) + 1
    substantial_outside_prefixes = sum(1 for c in outside_counts.values() if c >= 10)
    if own >= 10 and substantial_outside_prefixes >= 2:
        return "master_index"
    # Thin-volume master: a small general/cover volume can host the project's
    # master index. Its own bookmark count is tiny (Embassy 00-General has 8),
    # so the own>=10 floor misses it. Promote when outside entries vastly
    # outnumber own sheets and span multiple disciplines.
    outside_total = sum(outside_counts.values())
    own_sheets = len(sheets)
    if (
        outside_total >= 50
        and substantial_outside_prefixes >= 3
        and outside_total >= 5 * max(own_sheets, 1)
    ):
        return "master_index"
    # Sub-set master (#54): a sub-project volume ("Architectural - Shed")
    # carries the master index for its whole sub-set, but at sub-set scale —
    # own 7, outside S×4 + E×3 — far below the big-master thresholds above.
    # Exact-key matching makes this safe at low counts: outside entries must
    # name real sheets that physically exist in OTHER volumes of the project
    # (legend/finish/schedule codes never do), across >= 2 disciplines, and
    # the index must substantially cover its own volume's sheets.
    if project_sheet_keys is not None and sheets:
        own_sheet_keys = {normalize_sheet_number(s["sheet_number"]) for s in sheets}
        own_exact = 0
        outside_exact: dict[str, int] = {}
        for row in index_rows:
            key = normalize_sheet_number(row["sheet_number"])
            m = _SHEET_PREFIX_RE.match(row["sheet_number"])
            if key in own_sheet_keys:
                own_exact += 1
            elif key in project_sheet_keys and m:
                prefix = m.group(1).upper()
                outside_exact[prefix] = outside_exact.get(prefix, 0) + 1
        if (
            own_exact >= 0.5 * len(own_sheet_keys)
            and len(outside_exact) >= 2
            and sum(outside_exact.values()) >= 3
        ):
            return "master_index"
    return "volume_index"


def _keys_near_miss(a: str, b: str) -> bool:
    """Same-length normalized keys differing in at most 2 characters.

    Catches OCR/text-layer digit variance on an otherwise-real sheet number
    (index text `PK101` vs bookmark `PK-001` → normalized `PK101`/`PK001`,
    #80) without treating an unrelated same-prefix code as a match.
    """
    return len(a) == len(b) and 0 < sum(1 for x, y in zip(a, b) if x != y) <= 2


def _per_prefix_gate(
    region_rows: list[dict],
    volume_sheets: list[dict],
    project_bookmark_prefixes: set[str] | None,
    *,
    min_count: int = 3,
    min_coverage: float = 0.5,
    project_sheet_keys: set[str] | None = None,
) -> list[dict]:
    """Filter a region's rows to those from accepted prefixes.

    Acceptance rules per prefix P:
    1. P exists in this volume's bookmark sheets AND count(P in region) >= min_count
       AND coverage(region-P vs volume-P) >= min_coverage  → accepted (volume prefix).
    2. P does NOT exist in this volume's bookmarks but count(P in region) >= min_count
       AND P is a known project prefix (or project context absent) → accepted (CNL'd
       discipline: every sheet is listed but none are present in the set).
    2b. P does NOT exist in this volume's bookmarks, count(P in region) < min_count,
        but a specific row's key exactly matches (or near-misses, #80) a real
        project sheet key sharing prefix P → that row is accepted individually.
        Handles small disciplines with only 1-2 master-index rows (PK, TS on NE A
        Street) without reopening the door to unrelated single-hit prefix noise —
        only rows independently confirmed against the real project catalog admit.
    3. Anything else → dropped (legend scrape, single-hit noise).

    Returns the filtered row list.  An empty result means the whole region is junk.
    """
    volume_prefix_counts: dict[str, int] = {}
    for s in volume_sheets:
        m = _SHEET_PREFIX_RE.match(s["sheet_number"])
        if m:
            p = m.group(1).upper()
            volume_prefix_counts[p] = volume_prefix_counts.get(p, 0) + 1

    # Acceptance is decided on TITLED rows only. Number-only rows (#73
    # multi-column drops) ride along once their prefix is accepted, but must
    # not be able to flip acceptance themselves: elevation-key callouts and
    # schedule scrapes are title-less, and on Embassy's Interior Design volume
    # they pushed the I-prefix coverage past the gate, admitting eight
    # floor-plan pages as a phantom index region.
    titled_rows = [r for r in region_rows if (r.get("title") or "").strip()]
    region_prefix_counts: dict[str, int] = {}
    for row in titled_rows:
        m = _SHEET_PREFIX_RE.match(row["sheet_number"])
        if m:
            p = m.group(1).upper()
            region_prefix_counts[p] = region_prefix_counts.get(p, 0) + 1

    # Build volume sheet-key sets per prefix for coverage calculation
    volume_keys_by_prefix: dict[str, set[str]] = {}
    for s in volume_sheets:
        m = _SHEET_PREFIX_RE.match(s["sheet_number"])
        if m:
            p = m.group(1).upper()
            volume_keys_by_prefix.setdefault(p, set()).add(
                normalize_sheet_number(s["sheet_number"])
            )

    # First pass: determine which prefixes pass the "strong" gate (count >= min_count
    # and coverage >= min_coverage). A region with at least one strong-pass volume
    # prefix is a "primary index" region — we then also admit any other volume prefix
    # whose coverage alone is >= min_coverage regardless of count (handles small
    # disciplines like NCG01 that appear only once in a civil master index but cover
    # 100% of their 2-sheet prefix).
    strong_accepted: set[str] = set()
    coverage_by_prefix: dict[str, float] = {}
    for prefix, count in region_prefix_counts.items():
        if prefix not in volume_prefix_counts:
            continue
        vol_keys = volume_keys_by_prefix.get(prefix, set())
        region_keys = {
            normalize_sheet_number(r["sheet_number"])
            for r in titled_rows
            if _SHEET_PREFIX_RE.match(r["sheet_number"])
            and _SHEET_PREFIX_RE.match(r["sheet_number"]).group(1).upper() == prefix
        }
        cov = len(region_keys & vol_keys) / max(len(vol_keys), 1)
        coverage_by_prefix[prefix] = cov
        if count >= min_count and cov >= min_coverage:
            strong_accepted.add(prefix)

    is_primary_region = bool(strong_accepted)

    accepted_prefixes: set[str] = set(strong_accepted)
    for prefix, count in region_prefix_counts.items():
        if prefix in accepted_prefixes:
            continue
        if prefix in volume_prefix_counts:
            # Secondary volume prefix on a primary-region page: accept if coverage alone
            # is sufficient (small disciplines with fewer than min_count sheets).
            if is_primary_region and coverage_by_prefix.get(prefix, 0.0) >= min_coverage:
                accepted_prefixes.add(prefix)
        else:
            # Non-volume prefix: only on a primary-region page (region has at least one
            # strong volume-prefix). Without this, a schedule-body page whose rows
            # reference real project discipline codes (C, E, S ...) would generate
            # false CNLs even though no volume-prefix passes the gate on that page.
            if not is_primary_region:
                continue
            if count < min_count:
                continue
            if project_bookmark_prefixes is None or prefix in project_bookmark_prefixes:
                accepted_prefixes.add(prefix)

    # Rule 2b: rows whose prefix didn't clear min_count above (small disciplines,
    # #80) but whose specific key exactly matches — or near-misses — a real
    # project sheet key sharing that prefix. Row-level, not prefix-level: only
    # rows independently confirmed against the actual project catalog admit, so
    # an unrelated single-hit code sharing a common prefix stays excluded.
    #
    # Scoped to genuine multi-discipline MASTER index regions (>= 2 strongly
    # accepted prefixes) — a project master index legitimately carries small
    # 1-2 row discipline groups (PK, TS on NE A Street). A single-discipline
    # VOLUME index (exactly one strong prefix, e.g. Quarry Oaks's Interior
    # Design schedule) doesn't get this leniency: a stray same-string token
    # there (Quarry Oaks's `A101`, an incidental schedule/legend mention of
    # another volume's real sheet) is noise, not a dropped index row, even
    # though it happens to exactly match a real project key.
    accepted_row_keys: set[str] = set()
    if len(strong_accepted) >= 2 and project_sheet_keys:
        keys_by_prefix: dict[str, set[str]] = {}
        for k in project_sheet_keys:
            m = _SHEET_PREFIX_RE.match(k)
            if m:
                keys_by_prefix.setdefault(m.group(1).upper(), set()).add(k)
        for row in titled_rows:
            m = _SHEET_PREFIX_RE.match(row["sheet_number"])
            if not m:
                continue
            prefix = m.group(1).upper()
            if prefix in accepted_prefixes or prefix in volume_prefix_counts:
                continue
            row_key = normalize_sheet_number(row["sheet_number"])
            for candidate in keys_by_prefix.get(prefix, ()):
                if row_key == candidate or _keys_near_miss(row_key, candidate):
                    accepted_row_keys.add(row["sheet_number"])
                    break

    return [
        row for row in region_rows
        if row["sheet_number"] in accepted_row_keys
        or (
            (m := _SHEET_PREFIX_RE.match(row["sheet_number"]))
            and m.group(1).upper() in accepted_prefixes
        )
    ]


def _lead_sheet_at_page(sheets: list[dict], page: int) -> str | None:
    """Bookmark sheet number bound at ``page`` (the index region's lead sheet)."""
    for s in sheets:
        if s.get("page") == page:
            return s["sheet_number"]
    return None


def _discipline_prefix(sheet_number: str) -> str | None:
    m = _SHEET_PREFIX_RE.match(sheet_number or "")
    return m.group(1).upper() if m else None


def build_index_layers(
    regions: list[dict],
    sheets: list[dict],
    project_bookmark_prefixes: set[str] | None,
) -> list[dict]:
    """Classify each index region into a named layer (ADR-0026 / #88).

    One channel per discovered index layer, provenance-named by CONTEXT.md's
    two domain terms only:
      - ``master:<lead-sheet>``     — a general/cover-sheet index spanning >= 2
        disciplines (the whole-volume Master Index), auto-admitted.
      - ``discipline:<lead-sheet>`` — a single-discipline index on that
        discipline's lead sheet, admitted only after a Claude page read
        (confirmation_status='candidate').

    Rows are filtered to those whose discipline prefix is a real project prefix
    (drops finish/legend code noise) — deliberately NOT the strict per-prefix
    coverage gate, so a mis-bound master whose listed sheets are absent from its
    own volume (Valrico B16: index lists 16-S101, bound sheets are 6-S101…)
    survives as a candidate layer instead of being silently discarded.
    """
    layers: list[dict] = []
    used_prov: set[str] = set()
    for region in regions:
        header_pg = region["header_pg"]
        rows = region["rows"]
        page_of = region["page_of"]
        filtered = [
            r
            for r in rows
            if (dp := _discipline_prefix(r["sheet_number"]))
            and (project_bookmark_prefixes is None or dp in project_bookmark_prefixes)
        ]
        from collections import Counter

        disc_counts = Counter(
            dp for r in filtered if (dp := _discipline_prefix(r["sheet_number"]))
        )
        if not filtered or not disc_counts:
            continue
        dominant, dominant_ct = disc_counts.most_common(1)[0]
        # A discipline carries a real sub-section only if it has >= 2 rows; single
        # cross-discipline tokens (an "A2"/"D600"/"T1" legend/detail token on an
        # electrical index) are noise, not a sub-index. A region is a Master/cover
        # index only when >= 2 disciplines each clear that floor (even a garage
        # cover listing 1-2 sheets across disciplines — Valrico B16 has A/M/P x2);
        # otherwise it is a single-discipline Discipline Index.
        significant = [d for d, ct in disc_counts.items() if ct >= 2]
        lead = _lead_sheet_at_page(sheets, header_pg)
        # A Master Index lives on the general/cover sheet (G-prefixed lead:
        # x-G001 residential, x-G000 garage) and spans several disciplines. A
        # combined discipline index (some firms list Electrical + Technology
        # together on the E lead sheet) also spans >= 2 disciplines but is NOT a
        # master — its lead is a discipline sheet. Require a G lead (or, absent a
        # bookmark lead, >= 3 significant disciplines) to admit a master.
        is_general_lead = lead is not None and _discipline_prefix(lead) == "G"
        is_master = len(significant) >= 2 and (
            is_general_lead or (lead is None and len(significant) >= 3)
        )
        if not is_master:
            kind = "discipline"
            base = lead or f"p{header_pg}"
            status = "candidate"
            disc_prefix = dominant
            disciplines = {dominant}
        else:
            kind = "master"
            base = lead or f"cover-p{header_pg}"
            status = "admitted"
            disc_prefix = None
            disciplines = set(disc_counts)
        prov = f"{kind}:{base}"
        if prov in used_prov:
            prov = f"{prov}@p{header_pg}"
        used_prov.add(prov)
        # A discipline layer carries only its own discipline's rows; a couple of
        # foreign noise tokens are not part of that Discipline Index.
        layer_rows = (
            filtered
            if kind == "master"
            else [
                r
                for r in filtered
                if _discipline_prefix(r["sheet_number"]) == disc_prefix
            ]
        )
        layers.append(
            {
                "provenance": prov,
                "layer_kind": kind,
                "lead_sheet_number": lead,
                "index_page": header_pg,
                "discipline_prefix": disc_prefix,
                "confirmation_status": status,
                "signals": {
                    "index_header_page": header_pg,
                    "disciplines": sorted(disciplines),
                    "row_count": len(layer_rows),
                },
                "entries": [
                    {
                        "sheet_number": r["sheet_number"],
                        "title": r.get("title"),
                        "index_page": page_of.get(r["sheet_number"], header_pg),
                    }
                    for r in layer_rows
                ],
            }
        )
    return layers


def analyze_pdf(
    pdf_path: str | Path,
    *,
    config: DrawingIndexConfig | None = None,
    project_bookmark_prefixes: set[str] | None = None,
    project_sheet_keys: set[str] | None = None,
) -> dict:
    """Extract sheets, index entries, and cross-check samples from one drawing PDF.

    Multi-region discovery (issue #71): scans ALL pages for index headers and parses
    each region independently with its continuation walk. Accepted regions are unioned
    into the volume index; a per-prefix coverage gate replaces the old whole-volume
    gate so discipline-specific indexes mid-volume are found and accepted.
    """
    path = Path(pdf_path)
    cfg = config or DrawingIndexConfig()
    doc = fitz.open(path)
    try:
        sheets, parse_rate, bookmark_anomalies = extract_bookmarks(doc)
        page_texts = _extract_all_page_text(doc)
        all_header_pages = find_all_index_pages(doc, page_texts=page_texts)
        page_char_counts = [len(t) for t in page_texts]
        # Preserved even when every region's rows are rejected by the per-prefix
        # gate: the raw header detection is the extraction-blindness signal
        # (issue #75) — header present, zero usable rows ⇒ suspected raster.
        index_header_page = all_header_pages[0] if all_header_pages else None
        index_rows_parsed = 0
        index_entries: list[dict] = []
        index_pages: list[int] = []
        index_anomalies: list[dict] = []
        index_page: Optional[int] = all_header_pages[0] if all_header_pages else None

        # Collect all region start pages, deduplicating continuations so we don't
        # re-parse pages that belong to a region we already walked.
        covered_pages: set[int] = set()
        region_rows_all: list[dict] = []
        region_anomalies_all: list[dict] = []
        all_region_pages: list[int] = []
        index_duplicates: list[dict] = []
        # Per-region raw capture for the layer model (#88), independent of the
        # strict per-prefix gate below.
        regions_captured: list[dict] = []

        for header_pg in all_header_pages:
            if header_pg in covered_pages:
                continue
            continuation = _find_continuation_pages(
                doc,
                header_pg,
                project_bookmark_prefixes=project_bookmark_prefixes,
                page_texts=page_texts,
            )
            region_raw: list[dict] = []
            region_seen: set[str] = set()
            region_page_of: dict[str, int] = {}
            region_anoms: list[dict] = []
            page_dup_counts: dict[str, tuple[int, int]] = {}  # key -> (count, page)
            for p in continuation:
                covered_pages.add(p)
                txt = page_texts[p - 1]
                raw_lines = [ln.strip() for ln in txt.split("\n") if ln.strip()]
                for row in parse_index_page_text(txt):
                    key = row["sheet_number"]
                    if key in region_seen:
                        continue
                    region_seen.add(key)
                    region_page_of[key] = p
                    region_raw.append(row)
                for anom in extract_index_anomalies(raw_lines):
                    region_anoms.append({**anom, "page": p})
                # #76: a key repeated within THIS SAME page's index table is a
                # real duplicate row — distinct from region_seen's cross-page
                # dedup above (continuation overlap / master+volume both
                # listing a key, which is normal, not a duplicate).
                for dup_key, count in parse_index_page_duplicates(txt).items():
                    page_dup_counts[dup_key] = (count, p)

            regions_captured.append(
                {
                    "header_pg": header_pg,
                    "rows": list(region_raw),
                    "page_of": dict(region_page_of),
                }
            )

            # Per-prefix gate: keep only rows from accepted prefixes.
            filtered = _per_prefix_gate(
                region_raw,
                sheets,
                project_bookmark_prefixes,
                project_sheet_keys=project_sheet_keys,
            )
            if filtered:
                accepted_prefixes_here = {
                    m.group(1).upper()
                    for row in filtered
                    if (m := _SHEET_PREFIX_RE.match(row["sheet_number"]))
                }
                for row in filtered:
                    region_rows_all.append({**row, "_page": region_page_of[row["sheet_number"]]})
                region_anomalies_all.extend(region_anoms)
                all_region_pages.extend(continuation)
                # region_raw (pre-gate) so a duplicate's title is available
                # even when its prefix only clears the broader dup_prefixes_here
                # admission below, not the stricter per-prefix gate itself.
                title_by_key = {row["sheet_number"]: row.get("title") for row in region_raw}
                # A same-page repeat with two real titles is stronger evidence
                # of being real index content than a single occurrence, so a
                # prefix externally confirmed real (project_bookmark_prefixes)
                # is enough here even if it didn't individually clear the
                # stricter per-prefix gate above (NCG01 vs bookmarked
                # NCG01-1/NCG01-2 — different length, so the near-miss key
                # check in _per_prefix_gate doesn't admit it; the row-pairing
                # that key mismatch calls for is #85's job, not this one's).
                dup_prefixes_here = set(accepted_prefixes_here)
                if project_bookmark_prefixes:
                    for dup_key in page_dup_counts:
                        m = _SHEET_PREFIX_RE.match(dup_key)
                        if m and m.group(1).upper() in project_bookmark_prefixes:
                            dup_prefixes_here.add(m.group(1).upper())
                for dup_key, (count, page) in page_dup_counts.items():
                    m = _SHEET_PREFIX_RE.match(dup_key)
                    prefix = m.group(1).upper() if m else None
                    # Only report duplicates for keys whose prefix is accepted
                    # or externally confirmed (kills legend/schedule scrape
                    # noise on unrelated prefixes) — the key itself need not
                    # have individually survived region_seen's dedup.
                    if prefix not in dup_prefixes_here:
                        continue
                    title = title_by_key.get(dup_key)
                    if prefix not in accepted_prefixes_here:
                        # Externally-confirmed-only admission (didn't clear the
                        # stricter per-prefix gate) needs a substantive title —
                        # same bar as _find_continuation_pages — to rule out
                        # detail-callout/symbol-legend noise coincidentally
                        # sharing a real project prefix (NE A Street vol 6 p.19:
                        # "A101" from a detail bubble legend, title "1 SIM").
                        if not title or len(title) < 10 or title.strip("_").strip() == "":
                            continue
                    index_duplicates.append(
                        {
                            "sheet_number": dup_key,
                            "count": count,
                            "page": page,
                            "title": title,
                        }
                    )

        # Classify scope from the union of all accepted-region rows.
        source: Optional[str] = None
        if region_rows_all:
            source = classify_index_scope(
                sheets,
                region_rows_all,
                project_bookmark_prefixes=project_bookmark_prefixes,
                project_sheet_keys=project_sheet_keys,
            )
            # Dedupe by sheet key across regions; first occurrence wins.
            global_seen: set[str] = set()
            for row in region_rows_all:
                key = row["sheet_number"]
                if key in global_seen:
                    continue
                global_seen.add(key)
                index_entries.append(
                    {
                        "sheet_number": key,
                        "title": row.get("title"),
                        "source": source,
                        "index_page": row["_page"],
                    }
                )
            index_pages = sorted(set(all_region_pages))
            index_anomalies = region_anomalies_all
            for anom in index_anomalies:
                anom.setdefault("channel", source)
            for dup in index_duplicates:
                dup.setdefault("source", source)
            # Rows that SURVIVED the coverage gate — the extraction-blindness
            # signal counts usable rows, not raw scrapes (a raster header page
            # can still scrape a junk row or two).
            index_rows_parsed = len(index_entries)

        # Building-namespaced sets (#86/#88): switch to the per-layer channel
        # model. Guarded on building_prefix presence so ordinary single-building
        # / non-namespaced projects keep the exact flat master_index/volume_index
        # path above unchanged (Embassy/Atlas/QO/Juvenile/Kadlec precision).
        index_layers: list[dict] = []
        if any(s.get("building_prefix") for s in sheets):
            index_layers = build_index_layers(
                regions_captured, sheets, project_bookmark_prefixes
            )
            # Rebuild index_entries as ONE row per (layer, key) so every layer is
            # its own reconciliation channel (no cross-layer dedup — a key listed
            # in both master and a discipline index must appear in both channels).
            # `source` carries the provenance so the drawing_index_entries
            # UNIQUE(volume, sheet, source) admits the same key in several layers
            # (a key listed in both master and a discipline index). The
            # layer_kind lives in drawing_index_layers; legacy source-keyed
            # reconciliation is skipped for building sets.
            index_entries = []
            for layer in index_layers:
                for e in layer["entries"]:
                    index_entries.append(
                        {
                            "sheet_number": e["sheet_number"],
                            "title": e.get("title"),
                            "source": layer["provenance"],
                            "index_page": e.get("index_page"),
                            "layer_provenance": layer["provenance"],
                        }
                    )
            index_pages = sorted({lyr["index_page"] for lyr in index_layers})
            index_rows_parsed = len(index_entries)

        tb_mismatches: list[dict] = []
        if cfg.title_block_calibrated and sheets:
            tb_mismatches = titleblock_crosscheck(doc, sheets, cfg.title_block)

        return {
            "success": True,
            "sheets": sheets,
            "index_entries": index_entries,
            "index_layers": index_layers,
            "index_duplicates": index_duplicates,
            "titleblock_mismatches": tb_mismatches,
            "bookmark_anomalies": bookmark_anomalies,
            "index_anomalies": index_anomalies,
            "meta": {
                "total_pages": doc.page_count,
                "bookmark_parse_rate": round(parse_rate, 3),
                "index_page": index_page,
                "index_pages": index_pages,
                "index_scope": (
                    index_entries[0]["source"] if index_entries else None
                ),
                "bookmark_parse_warning": parse_rate < 0.5 and parse_rate > 0,
                "extraction_signal": compute_extraction_signal(
                    page_char_counts, index_header_page, index_rows_parsed
                ),
            },
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        doc.close()
