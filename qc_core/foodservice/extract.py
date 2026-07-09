"""Rotated-schedule extraction for foodservice and electrical kitchen schedules.

Both tables are printed rotated 90 degrees: each equipment item is a vertical
strip at a distinct x, each attribute (Volts, Amps, ...) is a horizontal band at
a distinct y marked by a rotated header label. We read a cell by intersecting an
item's x with an attribute's y-band.

The shared primitive is ``bin_cells``: given header label y-centers and item
x-centers, every data word is assigned to its nearest header center (by y) and
nearest item (by x). Words that fall too far from any center/item are dropped.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

# fitz "words" tuple indices: (x0, y0, x1, y1, text, block, line, word_no)
X0, Y0, X1, Y1, TXT = 0, 1, 2, 3, 4


def _cx(w) -> float:
    return (w[X0] + w[X1]) / 2


def _cy(w) -> float:
    return (w[Y0] + w[Y1]) / 2


def _words(page) -> list:
    return page.get_text("words")


def cluster_by_x(words: list, *, tol: float = 30.0) -> list[list]:
    """Group words into vertical stacks by near-equal x (rotated headers)."""
    stacks: list[list] = []
    for w in sorted(words, key=_cx):
        if stacks and _cx(w) - _cx(stacks[-1][-1]) <= tol:
            stacks[-1].append(w)
        else:
            stacks.append([w])
    return stacks


def bin_cells(
    words: list,
    centers: list[tuple[str, float]],
    items: list[tuple[str, float]],
    *,
    y_gap: float = 30.0,
    x_gap: float = 11.0,
) -> dict[str, dict[str, str]]:
    """Assign each word to (nearest item by x, nearest header center by y).

    ``centers`` is the FULL set of header labels in the block (so neighbouring
    columns form tight bands and don't steal values); callers read only the
    subset they care about. Returns item_key -> {label: joined cell text}.
    """
    buckets: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for w in words:
        cy = _cy(w)
        lbl, best = None, y_gap
        for name, y in centers:
            d = abs(cy - y)
            if d < best:
                best, lbl = d, name
        if lbl is None:
            continue
        cx = _cx(w)
        item, bestx = None, x_gap
        for key, x in items:
            d = abs(cx - x)
            if d < bestx:
                bestx, item = d, key
        if item is None:
            continue
        buckets[item][lbl].append(w)
    out: dict[str, dict[str, str]] = {}
    for item, cells in buckets.items():
        out[item] = {
            lbl: " ".join(t[TXT] for t in sorted(ws, key=lambda t: (round(t[Y0]), t[X0])))
            for lbl, ws in cells.items()
        }
    return out


# --------------------------------------------------------------------------- #
# Electrical Kitchen Equipment Schedule (E411)
# --------------------------------------------------------------------------- #

ELEC_HEADER = {
    "MARK", "DESCRIPTION", "VOLT", "PHASE", "HP", "WATTS", "AMPS",
    "HARDWIRED", "RECEPTACLE", "CONNECTION", "DISCONNECT", "HEIGHT",
    "FEEDER", "CIRCUIT",
}
ELEC_MARK_RE = re.compile(r"^[A-Z]\d{1,3}(?:\.\d{1,2}|[a-z])?$")


@dataclass
class ElecMark:
    mark: str
    description: str | None
    volt: str | None
    phase: str | None
    watts: str | None
    amps: str | None
    connection: str | None  # 'hardwired' | 'receptacle' | None
    disconnect: str | None
    height: str | None
    bbox: tuple[float, float, float, float]


def _stack_centers(stack: list) -> dict[str, float]:
    """Median y-center per distinct label in a header stack."""
    by_label: dict[str, list[float]] = defaultdict(list)
    for w in stack:
        by_label[w[TXT]].append(_cy(w))
    return {lbl: sorted(ys)[len(ys) // 2] for lbl, ys in by_label.items()}


# A rotated header spans far upward from its MARK label (MARK is the bottom
# column; CIRCUIT/FEEDER sit ~900pt above). One MARK header == one table block.
_HEADER_RISE = 950.0


def extract_elec_marks(page) -> list[ElecMark]:
    words = _words(page)
    header_words = [w for w in words if w[TXT] in ELEC_HEADER]
    mark_headers = [w for w in header_words if w[TXT] == "MARK"]

    results: list[ElecMark] = []
    for mh in mark_headers:
        hx, mark_y = _cx(mh), _cy(mh)
        col_words = [
            w for w in header_words
            if abs(_cx(w) - hx) <= 30 and mark_y - _HEADER_RISE <= _cy(w) <= mark_y + 30
        ]
        centers = _stack_centers(col_words)
        if not {"MARK", "VOLT", "AMPS"} <= set(centers):
            continue
        # Right boundary: the next header in the SAME horizontal table row
        # (similar mark_y). A header in a different row (stacked table) is not a
        # boundary, so a full-width row extends to the page edge.
        x_hi = min(
            (
                _cx(w) for w in mark_headers
                if _cx(w) > hx + 20 and abs(_cy(w) - mark_y) < 200
            ),
            default=page.rect.width + 1,
        )
        marks = [
            w for w in words
            if ELEC_MARK_RE.match(w[TXT])
            and hx < _cx(w) <= x_hi
            and abs(_cy(w) - mark_y) <= 12
        ]
        items = [(w[TXT], _cx(w)) for w in marks]
        block_words = [
            w for w in words
            if hx - 4 < _cx(w) <= x_hi
            and mark_y - _HEADER_RISE <= _cy(w) <= mark_y + 40
        ]
        center_list = list(centers.items())
        cells = bin_cells(block_words, center_list, items)
        for mark_w in marks:
            mk = mark_w[TXT]
            c = cells.get(mk, {})
            conn = (
                "hardwired" if "X" in c.get("HARDWIRED", "").upper()
                else "receptacle" if "X" in c.get("RECEPTACLE", "").upper()
                else None
            )
            results.append(
                ElecMark(
                    mark=mk,
                    description=c.get("DESCRIPTION"),
                    volt=c.get("VOLT"),
                    phase=c.get("PHASE"),
                    watts=c.get("WATTS"),
                    amps=c.get("AMPS"),
                    connection=conn,
                    disconnect=c.get("DISCONNECT"),
                    height=c.get("HEIGHT"),
                    bbox=(mark_w[X0], mark_w[Y0], mark_w[X1], mark_w[Y1]),
                )
            )
    return results


# --------------------------------------------------------------------------- #
# Foodservice Utility Schedule (QF*-2 sheets)
# --------------------------------------------------------------------------- #

# Anchor header words that mark the electrical-column y-bands. Map each to our
# canonical field. The schedule's plumbing/ventilation/steam columns sit at
# y-bands outside the electrical group and are excluded by the y-range bound.
FS_ANCHORS = {
    "Volts": "volts",
    "PH": "ph",
    "Amps": "amps",
    "KW": "kw",
    "HZ": "hz",
    "Type": "elec_conn_type",   # bottom line of "Elec. Conn. Type"
    "AFF": "elec_rough_in_aff",  # first (highest-y) AFF = Elec. Rough-In AFF
}
FS_ITEM_RE = re.compile(r"^[A-Z]\d{1,3}(?:\.\d{1,2})?$")


@dataclass
class FsItem:
    item_number: str
    qty: str | None
    description: str | None
    volts: str | None
    ph: str | None
    amps: str | None
    kw: str | None
    hz: str | None
    elec_conn_type: str | None
    elec_rough_in_aff: str | None
    bbox: tuple[float, float, float, float]


def _fs_strip_xs(words: list) -> list[float]:
    """A foodservice sheet can carry several side-by-side schedule strips, each
    with its own rotated header column (a ``Volts`` label). Return each strip's
    header x, left to right."""
    return sorted(_cx(w) for w in words if w[TXT] == "Volts")


def extract_fs_items(page) -> list[FsItem]:
    words = _words(page)
    strip_xs = _fs_strip_xs(words)
    out: list[FsItem] = []
    for i, hx in enumerate(strip_xs):
        x_hi = strip_xs[i + 1] if i + 1 < len(strip_xs) else page.rect.width + 1
        out.extend(_extract_fs_strip(words, hx, x_hi))
    return out


def _extract_fs_strip(words: list, hx: float, x_hi: float) -> list[FsItem]:
    """Extract the items of one schedule strip whose header column is at ``hx``
    and whose item columns span x in (hx, x_hi)."""

    # Header anchor y-centers, restricted to the header stack x (~hx).
    def anchor_y(label: str, pick_max: bool = False) -> float | None:
        ys = [_cy(w) for w in words if w[TXT] == label and abs(_cx(w) - hx) <= 18]
        if not ys:
            return None
        return max(ys) if pick_max else sorted(ys)[len(ys) // 2]

    centers: dict[str, float] = {}
    for label, field_name in FS_ANCHORS.items():
        y = anchor_y(label, pick_max=(label == "AFF"))
        if y is not None:
            centers[field_name] = y
    if "volts" not in centers or "elec_rough_in_aff" not in centers:
        return []

    # Values sit slightly below their (rotated) header center, so pad the slice
    # generously below AFF; bin_cells' y_gap still drops the plumbing columns.
    y_top = centers["volts"] + 12      # just above Volts
    y_bot = centers["elec_rough_in_aff"] - 25  # below Elec. Rough-In AFF value

    # Item columns: the item-number tokens. They appear at the very top and
    # bottom of each column; use the bottom band (largest-y cluster).
    item_words = [
        w for w in words
        if FS_ITEM_RE.match(w[TXT]) and hx + 4 < _cx(w) <= x_hi
    ]
    if not item_words:
        return []
    bottom_y = max(_cy(w) for w in item_words)
    item_band = [w for w in item_words if abs(_cy(w) - bottom_y) <= 30]
    if len(item_band) < 2:  # fall back to top band
        top_y = min(_cy(w) for w in item_words)
        item_band = [w for w in item_words if abs(_cy(w) - top_y) <= 30]
    items = [(w[TXT], _cx(w)) for w in item_band]

    # Description / QTY bands (single anchors, read separately and loosely).
    qty_y = anchor_y("QTY")
    desc_y = next(
        (_cy(w) for w in words if w[TXT] == "Description" and abs(_cx(w) - hx) <= 18),
        None,
    )

    center_list = [(f, y) for f, y in centers.items()]
    elec_words = [
        w for w in words
        if y_bot <= _cy(w) <= y_top and hx < _cx(w) <= x_hi
    ]
    cells = bin_cells(elec_words, center_list, items)

    # QTY: a single value token per item column near qty_y.
    qty_by_item: dict[str, str] = {}
    if qty_y is not None:
        qty_band = [w for w in words if abs(_cy(w) - qty_y) <= 14]
        for mk, x in items:
            tok = [w[TXT] for w in qty_band if abs(_cx(w) - x) <= 9]
            if tok:
                qty_by_item[mk] = " ".join(tok)

    # Description: tokens in the Description band, dropping the repeated item
    # number and a standalone qty integer. Rotated text reads bottom-to-top.
    desc_by_item: dict[str, str] = {}
    if desc_y is not None:
        desc_band = [w for w in words if abs(_cy(w) - desc_y) <= 80]
        for mk, x in items:
            toks = sorted(
                (w for w in desc_band if abs(_cx(w) - x) <= 7),
                key=lambda w: -w[Y0],
            )
            words_out = [
                w[TXT] for w in toks
                if w[TXT] != mk and not w[TXT].isdigit()
            ]
            if words_out:
                desc_by_item[mk] = " ".join(words_out)

    out: list[FsItem] = []
    for mk, x in items:
        c = cells.get(mk, {})
        out.append(
            FsItem(
                item_number=mk,
                qty=qty_by_item.get(mk),
                description=desc_by_item.get(mk),
                volts=c.get("volts"),
                ph=c.get("ph"),
                amps=c.get("amps"),
                kw=c.get("kw"),
                hz=c.get("hz"),
                elec_conn_type=c.get("elec_conn_type"),
                elec_rough_in_aff=c.get("elec_rough_in_aff"),
                bbox=(x - 6, y_bot, x + 6, y_top),
            )
        )
    return out
