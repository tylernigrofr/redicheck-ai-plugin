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
    r"^([A-Z]{1,4}[-\.]?[\d\.]+[a-z]{0,4})(?:\s*[-–]\s*(.+))?",
    re.IGNORECASE,
)
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
_SHEET_PREFIX_RE = re.compile(r"^([A-Z]{1,4})")


def normalize_sheet_number(raw: str) -> str:
    """Comparison key — collapse whitespace and hyphens (legacy compare_with_index)."""
    return re.sub(r"[\s\-]+", "", raw.strip().upper())


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
    return bool(re.match(r"^[A-Z]", sn))


def extract_bookmarks(doc: fitz.Document) -> tuple[list[dict], float]:
    """Depth-2 TOC entries as sheet catalog (method A)."""
    depth2 = 0
    parsed: list[dict] = []
    for level, title, page in doc.get_toc():
        if level != 2:
            continue
        depth2 += 1
        m = BOOKMARK_RE.match(title.strip())
        if not m:
            continue
        parsed.append(
            {
                "sheet_number": m.group(1).upper(),
                "title": (m.group(2) or "").strip(),
                "page": int(page),
                "confidence": "high",
            }
        )
    rate = (len(parsed) / depth2) if depth2 else 0.0
    return parsed, rate


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


def find_index_page(doc: fitz.Document, *, max_pages: int = 15) -> Optional[int]:
    """1-based page number with index header, or None (method B)."""
    for i in range(min(max_pages, doc.page_count)):
        txt = doc[i].get_text("text") or ""
        if INDEX_PAGE_RE.search(txt) or INDEX_PAGE_RE.search(_collapse_letterspacing(txt)):
            return i + 1
    return None


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
    r"(?:"
    r"[A-Z]{1,4}-?\d{1,4}(?:[A-Za-z]{0,4}|\.(?:\d[A-Za-z0-9]{0,3}|[A-Za-z]{1,2})(?:\.(?:\d{1,3}|[A-Za-z]{1,2}))?)"
    r"|[A-Z]{1,4}\.\d{1,4}[A-Za-z]{0,3}"
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
    pm = _SHEET_PREFIX_RE.match(token)
    prefix = pm.group(1) if pm else ""
    if len(prefix) < 2 and token.count(".") < 2:
        return None
    return token, m.group(2).strip()


def _parse_index_lines(lines: list[str]) -> list[dict]:
    """Walk lines, emit one entry per `SheetNum → Title` pair.

    Index tables list `SheetNum / Title / [issuance / date]` per row. A real
    entry is a sheet-shaped line whose immediate successor is a non-sheet,
    non-digit-leading line shorter than 100 chars (the title). Tokens that
    appear in title blocks / project directories typically lack that follower
    or are followed by another sheet-shaped token, so this filter drops most
    of the token-scrape noise (e.g. abbreviation codes on legend pages).
    Multi-line titles are accepted by greedy-extending to the next sheet line.
    """
    entries: list[dict] = []
    seen: set[str] = set()
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
            i += 1
            continue
        # Drop symbol-legend entries — labels like "DENOTES SECTION LETTER"
        # appear alongside sheet-shaped tokens (e.g. "S1.0") on some index
        # pages as part of a symbols legend, not as real sheet entries.
        # Also poison `seen` so later occurrences of the same token on the
        # same legend (with a different annotation) get suppressed too.
        if re.match(r"^\s*DENOTES\b", title_parts[0], re.IGNORECASE):
            seen.add(token)
            i = j
            continue
        if token in seen:
            i = j
            continue
        seen.add(token)
        entries.append({"sheet_number": token, "title": " ".join(title_parts).strip()})
        i = j
    return entries


def _find_continuation_pages(
    doc: fitz.Document,
    start_page: int,
    *,
    max_extra: int = 10,
    project_bookmark_prefixes: set[str] | None = None,
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
        txt = doc[i].get_text("text") or ""
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
    return "volume_index"


def analyze_pdf(
    pdf_path: str | Path,
    *,
    config: DrawingIndexConfig | None = None,
    project_bookmark_prefixes: set[str] | None = None,
) -> dict:
    """Extract sheets, index entries, and cross-check samples from one drawing PDF."""
    path = Path(pdf_path)
    cfg = config or DrawingIndexConfig()
    doc = fitz.open(path)
    try:
        sheets, parse_rate = extract_bookmarks(doc)
        index_page = find_index_page(doc)
        index_entries: list[dict] = []
        index_pages: list[int] = []
        if index_page is not None:
            # Walk forward across continuation pages (some firms split the index across
            # multiple consecutive pages without repeating the INDEX header).
            index_pages = _find_continuation_pages(
                doc, index_page, project_bookmark_prefixes=project_bookmark_prefixes
            )
            raw_rows_all: list[dict] = []
            seen_keys: set[str] = set()
            page_of: dict[str, int] = {}
            for p in index_pages:
                txt = doc[p - 1].get_text("text") or ""
                for row in parse_index_page_text(txt):
                    key = row["sheet_number"]
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    page_of[key] = p
                    raw_rows_all.append(row)
            source = classify_index_scope(
                sheets, raw_rows_all, project_bookmark_prefixes=project_bookmark_prefixes
            )
            # Reject non-drawing-index parses (finish schedules, equipment legends,
            # material codes, etc.) when classified as volume_index. A real
            # volume drawing-index must cover a meaningful fraction of the
            # volume's own title-block sheets; a finish schedule's "entries"
            # don't share prefixes with the bookmark catalog. Skip the check for
            # master_index (its own-volume sheet count is often tiny by design).
            if source == "volume_index" and sheets:
                own_prefixes_local = _prefixes(s["sheet_number"] for s in sheets)
                own_entry_keys = {
                    normalize_sheet_number(r["sheet_number"])
                    for r in raw_rows_all
                    if (m := _SHEET_PREFIX_RE.match(r["sheet_number"]))
                    and m.group(1).upper() in own_prefixes_local
                }
                own_sheet_keys = {normalize_sheet_number(s["sheet_number"]) for s in sheets}
                coverage = (
                    len(own_entry_keys & own_sheet_keys) / max(len(own_sheet_keys), 1)
                )
                if coverage < 0.5:
                    raw_rows_all = []
                    index_pages = []
                    index_page = None
            for row in raw_rows_all:
                index_entries.append(
                    {
                        "sheet_number": row["sheet_number"],
                        "title": row.get("title"),
                        "source": source,
                        "index_page": page_of[row["sheet_number"]],
                    }
                )

        tb_mismatches: list[dict] = []
        if cfg.title_block_calibrated and sheets:
            tb_mismatches = titleblock_crosscheck(doc, sheets, cfg.title_block)

        return {
            "success": True,
            "sheets": sheets,
            "index_entries": index_entries,
            "titleblock_mismatches": tb_mismatches,
            "meta": {
                "total_pages": doc.page_count,
                "bookmark_parse_rate": round(parse_rate, 3),
                "index_page": index_page,
                "index_pages": index_pages,
                "index_scope": (
                    index_entries[0]["source"] if index_entries else None
                ),
                "bookmark_parse_warning": parse_rate < 0.5 and parse_rate > 0,
            },
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        doc.close()
