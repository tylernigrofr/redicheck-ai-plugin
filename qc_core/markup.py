"""Shared PDF markup styling and mechanics for every emit module (ADR-0012).

All QC emit paths — spec, drawing index, door schedule — write the same red,
bold, Bluebeam-Revu-native FreeText callout. This module is the single source of
truth for that appearance (colors, font, box geometry, rich text) and the
surrounding mechanics (date stamps, placement, idempotent rewrite, save). Emit
modules supply only the domain-specific manifest and the on-page anchor; they
never re-implement styling.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# --- Appearance: Bluebeam Revu "Red" FreeText callout ---
FONT_SIZE = 14.0
LINE_HEIGHT = 16.0       # one row; matches Revu's auto-sized box height at 14pt
HUG_PAD = 1.0            # horizontal slack so the box hugs the text like Revu
MAX_W = 280.0           # long comments wrap here instead of running off-page
GAP = 8.0               # gap between anchor and box
STACK_GAP = 2.0         # vertical gap when stacking boxes that would overlap
MARGIN = 4.0            # keep boxes this far from the page edge
RED = (1.0, 0.0, 0.0)    # Bluebeam default "Red" swatch
RED_HEX = "#FF0000"
RED_DA = "1 0 0 rg"      # Revu's color-only /DA for red FreeText
WHITE = (1.0, 1.0, 1.0)


@dataclass
class EmitResult:
    emitted: int = 0
    skipped_existing: int = 0
    unmatched: list = field(default_factory=list)
    output_path: Path | None = None


def pdf_date(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return "D:" + dt.strftime("%Y%m%d%H%M%S") + "Z"


def box_size_for(comment: str) -> tuple[float, float]:
    """Hug the text like Bluebeam: a tight single line for short comments,
    wrapping to `MAX_W` only when the text would otherwise exceed it."""
    import fitz

    text = comment or ""
    text_w = fitz.get_text_length(text, fontname="hebo", fontsize=FONT_SIZE)
    hug_w = text_w + 2 * HUG_PAD
    if hug_w <= MAX_W:
        return hug_w, LINE_HEIGHT
    inner_w = MAX_W - 2 * HUG_PAD
    lines = max(1, int(-(-text_w // inner_w)))  # ceil division
    return MAX_W, lines * LINE_HEIGHT


def place_box(page, anchor, w: float, h: float):
    """Place a w×h box adjacent to `anchor`, preferring right, then left, then
    below; clamp into the page if no candidate fits cleanly."""
    import fitz

    pw, ph = page.rect.width, page.rect.height
    candidates = [
        fitz.Rect(anchor.x1 + GAP, anchor.y0 - 2, anchor.x1 + GAP + w, anchor.y0 - 2 + h),
        fitz.Rect(anchor.x0 - GAP - w, anchor.y0 - 2, anchor.x0 - GAP, anchor.y0 - 2 + h),
        fitz.Rect(anchor.x0, anchor.y1 + GAP, anchor.x0 + w, anchor.y1 + GAP + h),
    ]
    for box in candidates:
        if box.x0 >= MARGIN and box.x1 <= pw - MARGIN and box.y0 >= MARGIN and box.y1 <= ph - MARGIN:
            return box
    box = candidates[0]
    x0 = max(MARGIN, min(box.x0, pw - w - MARGIN))
    y0 = max(MARGIN, min(box.y0, ph - h - MARGIN))
    return fitz.Rect(x0, y0, x0 + w, y0 + h)


def stack_clear(box, existing, page_rect):
    """If `box` overlaps any rect in `existing`, shift down until clear or off-page."""
    import fitz

    h = box.y1 - box.y0
    step = h + STACK_GAP
    max_y = page_rect.y1 - MARGIN
    while any(box.intersects(b) for b in existing):
        new_y0 = box.y0 + step
        if new_y0 + h > max_y:
            return box
        box = fitz.Rect(box.x0, new_y0, box.x1, new_y0 + h)
    return box


def find_rect_on_page(page, terms: Iterable[str]):
    for term in terms:
        if not term:
            continue
        hits = page.search_for(term)
        if hits:
            return hits[0]
    return None


def rich_text_payload(
    comment: str, font_size: float = FONT_SIZE, color_hex: str = RED_HEX
) -> tuple[str, str]:
    """Return (/DS string, /RC XHTML) byte-for-byte in Bluebeam Revu's dialect.

    Reviewers triage these in Revu, so we emit the exact rich-text shape Revu
    writes itself — same `font: bold Helvetica-Bold` shorthand, `margin:0pt`,
    `line-height`, and `xfa:APIVersion="BluebeamPDFRevu:2018"`. Matching Revu's
    own serialization means it treats the annotation as native and never
    reformats /AP from /DA on edit-mode toggle.
    """
    line_height = round(font_size * 1.15, 1)  # Revu's 14pt -> 16.1pt
    style = (
        f"font:bold Helvetica-Bold {font_size:g}pt; text-align:left; "
        f"margin:0pt; line-height:{line_height:g}pt; color:{color_hex}"
    )
    ds = (
        f"font: bold Helvetica-Bold {font_size:g}pt; text-align:left; "
        f"margin:0pt; line-height:{line_height:g}pt; color:{color_hex}"
    )
    safe = html.escape(comment or "")
    rc = (
        '<?xml version="1.0"?>'
        '<body xmlns:xfa="http://www.xfa.org/schema/xfa-data/1.0/" '
        'xfa:contentType="text/html" '
        'xfa:APIVersion="BluebeamPDFRevu:2018" xfa:spec="2.2.0" '
        f'style="{style}" '
        'xmlns="http://www.w3.org/1999/xhtml">'
        '<p>'
        f'<span style="font-size:{font_size:g}pt; font-family:Helvetica-Bold; '
        f'font-weight:bold; color:{color_hex}">'
        f'{safe}'
        '</span></p></body>'
    )
    return ds, rc


def delete_markups(doc, subject_prefix: str) -> None:
    """Delete every annotation whose Subject starts with `<subject_prefix>:`.

    Re-running emit deletes prior markups and rewrites them, so a project never
    accumulates duplicates across runs.
    """
    for page in doc:
        to_delete = []
        for annot in page.annots() or []:
            info = annot.info or {}
            subj = info.get("subject") or ""
            if subj.startswith(f"{subject_prefix}:"):
                to_delete.append(annot)
        for annot in to_delete:
            page.delete_annot(annot)


def add_freetext_markup(
    doc,
    page,
    anchor,
    *,
    comment: str,
    reviewer: str,
    subject: str,
    now_pdf: str,
    placed_by_page: dict,
):
    """Add one red Revu-style FreeText callout near `anchor` and return the annot.

    `placed_by_page` accumulates placed boxes per page number so overlapping
    callouts stack downward instead of colliding.
    """
    import fitz

    w, h = box_size_for(comment)
    box = place_box(page, anchor, w, h)
    existing = placed_by_page.setdefault(page.number, [])
    box = stack_clear(box, existing, page.rect)
    existing.append(box)

    annot = page.add_freetext_annot(
        box,
        comment,
        fontsize=FONT_SIZE,
        fontname="HeBo",  # Helvetica-Bold
        text_color=RED,
        # Solid white box at full opacity so red text stays legible over
        # underlying linework/text (opacity stays global-opaque per #46).
        fill_color=WHITE,
        align=fitz.TEXT_ALIGN_LEFT,
    )
    annot.set_border(width=0)
    annot.set_info(
        title=reviewer,
        subject=subject,
        content=comment,
        creationDate=now_pdf,
        modDate=now_pdf,
    )
    # Lock contents so Revu doesn't auto-refit text on edit-mode toggle.
    annot.set_flags(annot.flags | fitz.PDF_ANNOT_IS_LOCKED_CONTENTS)
    annot.update()

    ds, rc = rich_text_payload(comment)
    doc.xref_set_key(annot.xref, "DS", f"({ds})")
    doc.xref_set_key(annot.xref, "RC", f"({rc})")
    doc.xref_set_key(annot.xref, "DA", f"({RED_DA})")
    return annot


def resolve_output_path(
    src: Path, output_path: Path | str | None, in_place: bool
) -> Path:
    if in_place:
        return src
    if output_path is None:
        return src.with_name(f"{src.stem}.marked.pdf")
    return Path(output_path)


def save_doc(doc, src: Path, out: Path, in_place: bool) -> None:
    if in_place:
        tmp = src.with_suffix(src.suffix + ".tmp")
        doc.save(tmp, deflate=True)
        doc.close()
        tmp.replace(src)
    else:
        doc.save(out, deflate=True)
        doc.close()
