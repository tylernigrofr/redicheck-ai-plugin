"""Infer RediCheck sheet discipline from sheet number + bookmark title (ADR-0023, issue #32)."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Fire Protection / Mechanical / Plumbing are distinct disciplines (#55);
# "Mechanical/Plumbing" survives only as the combined label for genuinely
# combined MEP volumes where the sheet prefix cannot split them.
CANONICAL_DISCIPLINES = frozenset(
    {
        "Civil",
        "Structural",
        "Architectural",
        "Fire Protection",
        "Mechanical",
        "Plumbing",
        "Mechanical/Plumbing",
        "Electrical",
        "Food Service",
        "Specifications",
    }
)

_MULTI = sorted(
    {
        ("FS", "Food Service"),
        ("QF", "Food Service"),
        ("AV", "Electrical"),
        ("EE", "Electrical"),
        ("EF", "Electrical"),
        ("TA", "Electrical"),
        ("TE", "Electrical"),
        ("TG", "Electrical"),
        ("TI", "Electrical"),
        ("LC", "Electrical"),
        ("LV", "Electrical"),
        ("EL", "Electrical"),
        ("EC", "Electrical"),
        ("ES", "Electrical"),
        ("FP", "Fire Protection"),
        ("MD", "Mechanical"),
        ("ME", "Mechanical"),
        ("MF", "Mechanical"),
        ("MH", "Mechanical"),
        ("MR", "Mechanical"),
        ("MV", "Mechanical"),
        ("MC", "Mechanical"),
        ("MP", "Mechanical/Plumbing"),
        ("MEP", "Mechanical/Plumbing"),
        ("PS", "Plumbing"),
        ("LI", "Civil"),
        ("CW", "Architectural"),
        ("CV", "Civil"),
        ("CI", "Civil"),
        ("SD", "Structural"),
        ("ID", "Architectural"),
        ("AD", "Architectural"),
        ("AE", "Architectural"),
        ("AR", "Architectural"),
        ("AH", "Architectural"),
        ("AJ", "Architectural"),
        ("AO", "Architectural"),
        ("AX", "Architectural"),
        ("AS", "Architectural"),
        ("AQ", "Architectural"),
        ("SP", "Specifications"),
    },
    key=lambda x: (-len(x[0]), x[0]),
)

_TITLE_KEYS = (
    ("AUDIO VISUAL", "Electrical"),
    ("COMMUNICATION", "Electrical"),
    (" SECURITY", "Electrical"),
    ("SECURITY PLAN", "Electrical"),
    ("TECHNOLOGY", "Electrical"),
    ("LOW VOLTAGE", "Electrical"),
    (" LIFE SAFETY", "Architectural"),
    ("LIFE SAFETY", "Architectural"),
    (" IRRIGATION", "Civil"),
    ("IRRIGATION", "Civil"),
    ("LANDSCAPE", "Civil"),
    (" PLANTING", "Civil"),
    ("HARDSCAPE", "Civil"),
    ("STRUCTURAL NOTES", "Structural"),
    ("STRUCTURAL PLAN", "Structural"),
    ("STRUCTURAL DETAIL", "Structural"),
    (" FIRE PROTECTION", "Fire Protection"),
    ("FIRE PROTECTION", "Fire Protection"),
    ("SPRINKLER", "Fire Protection"),
    (" HVAC", "Mechanical"),
    ("MECHANICAL", "Mechanical"),
    (" RECIRCULATION", "Plumbing"),
    (" PLUMBING", "Plumbing"),
    (" DEMOLISH", "Architectural"),
    ("DEMOLISH", "Architectural"),
    ("DEMO PLAN", "Architectural"),
    ("FOODSERVICE", "Food Service"),
    ("FOOD SERVICE", "Food Service"),
    ("TITLE SHEET", "Architectural"),
    ("EQUIPMENT FLOOR PLAN", "Architectural"),
    ("EQUIPMENT OVERALL PLAN", "Architectural"),
    ("EQUIPMENT LAYOUT", "Architectural"),
)

_VOL_STRIP_RE = re.compile(r"(?i)^\d{2}[-_\s]+")
_SINGLE = {
    "A": "Architectural",
    "E": "Electrical",
    "M": "Mechanical",
    "P": "Plumbing",
    "S": "Structural",
    "C": "Civil",
    "L": "Civil",
    "G": "Architectural",
    "I": "Architectural",
    "T": "Electrical",
    "K": "Food Service",
    "F": "Fire Protection",
}


def title_discipline_hint(title: str | None) -> str | None:
    if not title:
        return None
    up = title.upper()
    if "MECHANICAL" in up and "PLUMBING" in up:
        return "Mechanical/Plumbing"
    for needle, disc in _TITLE_KEYS:
        if needle in up:
            return disc
    return None


def _infer_ls(sn: str, title: str | None) -> tuple[str | None, bool]:
    u = title.upper() if title else ""
    if "LANDSCAPE" in u:
        return "Civil", False
    if any(x in u for x in ("LIFE SAFETY", " LIFE-SAFETY", "SMOKE COMPARTMENT")):
        return "Architectural", False
    if "CODE ANALYSIS" in u:
        return "Architectural", False
    if u.startswith("FGI") or "FGI " in u or "FGI FLOOR PLAN" in u:
        return "Architectural", False

    if re.match(r"^LS-\d+[.]", sn):
        return "Architectural", False
    # Hyphen + digit block with no fractional part: Kadlec landscapes use LS-001 / LS-101;
    # other projects may use LS-40 for life safety (title resolves).
    hyphen_m = re.match(r"^LS-(\d+)$", sn)
    if hyphen_m:
        digits = hyphen_m.group(1)
        if len(digits) >= 3:
            return "Civil", False
        return None, True
    if re.match(r"^LS\d", sn):
        return "Architectural", False
    return None, True


def _boundary_ok(pref: str, sn: str) -> bool:
    tail = sn[len(pref) :] if len(sn) >= len(pref) else ""
    if not tail:
        return True
    if tail[0].isdigit():
        return True
    if tail[0] in "-.":
        rest = tail[1:]
        return rest != "" and rest[0].isdigit()
    return False


def _multiletter_disc(sn: str) -> str | None:
    for prefix, discipline in _MULTI:
        if sn.startswith(prefix) and _boundary_ok(prefix, sn):
            return discipline
    return None


def _lead_letters(sn: str) -> str:
    letters = []
    for ch in sn:
        if ch.isalpha():
            letters.append(ch.upper())
        else:
            break
    return "".join(letters)


def normalize_volume_hint(raw: str | None) -> str | None:
    if not raw:
        return None
    stem = raw.strip().lower().replace(",", " ")
    stem = _VOL_STRIP_RE.sub("", stem)
    lc = " ".join(stem.split())
    nospace = lc.replace(" ", "")

    if "foodservice" in nospace or "food service" in lc:
        return "Food Service"
    if lc == "drawings.pdf" or stem == "drawings":
        return None
    if "mep" in nospace:
        return "Mechanical/Plumbing"
    if "drawing vol 5" in lc and ("comm" in lc or "security" in lc or "electrical" in lc):
        return "Electrical"
    if "electrical," in lc and "comm" in lc:
        return "Electrical"
    if lc.startswith("00-general") or lc.startswith("general"):
        return "Architectural"
    if lc.startswith("01 civil") or "civil" in lc.split():
        return "Civil"
    if lc.startswith("02-land"):
        return "Civil"
    if "architecture" in lc:
        return "Architectural"
    if "aquatics" in lc:
        return "Architectural"
    if lc.startswith("04-food") or "food service" in lc:
        return "Food Service"
    if "fire protection" in lc or "fireprotection" in nospace:
        return "Fire Protection"
    if lc.startswith("07-mechanical"):
        return "Mechanical"
    if lc.startswith("12 electrical") or lc.startswith("12-electrical"):
        return "Electrical"
    if "interiors" in lc or " interior" in lc or lc.startswith("13-interiors"):
        return "Architectural"
    if lc.startswith("02 life"):
        return "Architectural"
    if lc.startswith("05 landscape"):
        return "Civil"
    if "structural" in lc:
        return "Structural"
    if "life safety" in lc:
        return "Architectural"
    if any(x in lc for x in ("electrical", "lighting")):
        return "Electrical"
    if "mechanical" in lc and "plumbing" in lc:
        return "Mechanical/Plumbing"
    if "mechanical" in lc:
        return "Mechanical"
    if "plumbing" in lc:
        return "Plumbing"
    if any(x in lc for x in ("communication", "communications", "security", "technology")):
        return "Electrical"
    return None


@dataclass(frozen=True)
class SheetDisciplineResult:
    discipline: str
    needs_resolution: bool
    rationale: str


def infer_sheet_discipline(
    sheet_number: str | None,
    title: str | None,
    *,
    volume_discipline_hint: str | None = None,
) -> SheetDisciplineResult:
    sn = (sheet_number or "").strip().upper().replace(" ", "")
    # Strip a leading building-namespace segment ("16-S101" → "S101", #86) so
    # discipline inference reads the discipline prefix, not the building digits.
    sn = re.sub(r"^\d{1,2}-(?=[A-Z])", "", sn)
    vc = normalize_volume_hint(volume_discipline_hint)

    if not sn:
        fb = vc or "Architectural"
        return SheetDisciplineResult(fb, vc is None, "missing_sheet_number")

    # LS*: title + hyphen/digit-shape disambiguation (fixtures: Kadlec, Quarry Oaks).
    if sn.startswith("LS"):
        ls_d, ambiguous = _infer_ls(sn, title)
        if ls_d is not None:
            return SheetDisciplineResult(ls_d, False, "ls_prefix")
        fb = vc or "Architectural"
        return SheetDisciplineResult(fb, True, "ambiguous_ls_prefix")

    title_d = title_discipline_hint(title)
    prefix_d = _multiletter_disc(sn)

    lead = _lead_letters(sn)

    single_d: str | None = None
    if prefix_d is None and lead:
        if lead[0] == "D":
            if title_d:
                return SheetDisciplineResult(title_d, False, "d_prefix_title_hint")
            t = title or ""
            u = t.upper()
            if "SECURITY" in u or "COMMUNICATION" in u:
                return SheetDisciplineResult("Electrical", False, "d_prefix_keywords")
            if vc:
                return SheetDisciplineResult(vc, True, "d_prefix_volume_fallback")
            return SheetDisciplineResult("Architectural", True, "d_prefix_unknown")
        if lead[0] == "Q":
            u = (title or "").upper()
            if "COMMUNICATION" in u or "NETWORK" in u or "DATA" in u:
                return SheetDisciplineResult("Electrical", False, "q_prefix_comm_keywords")
            return SheetDisciplineResult("Architectural", False, "q_prefix_equipment_or_misc")

        if len(lead) == 1 and lead[0] in _SINGLE:
            single_d = _SINGLE[lead[0]]

    base = prefix_d or single_d
    discipline = title_d or base or vc or "Architectural"
    rationale = ""

    needs = False
    if title_d and base and title_d != base:
        rationale = "title_vs_prefix_conflict"
    elif base is None and title_d:
        rationale = "title_fallback"
    elif base is None and vc and title_d is None:
        rationale = "volume_fallback"
        needs = True
    elif base is None and vc is None and title_d is None:
        rationale = "architectural_default"
        needs = True

    return SheetDisciplineResult(discipline, needs, rationale or "prefix_or_title")
