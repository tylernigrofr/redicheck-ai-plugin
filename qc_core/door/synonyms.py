"""Canonical door schedule column synonyms (CONTEXT.md / ADR-0006)."""

from __future__ import annotations

import re

CANONICAL_FIELDS = (
    "door_no",
    "width",
    "height",
    "door_material",
    "frame_material",
    "fire_rating",
    "hardware_set",
)

# Normalized label -> canonical field. Longer / more specific labels first at match time.
SYNONYMS: dict[str, str] = {
    "MARK": "door_no",
    "NUMBER": "door_no",
    "SIZE": "width",
    "SIZE DOOR": "width",
    "DOOR SIZE": "width",
    "NO": "door_no",
    "NO.": "door_no",
    "DOOR NO": "door_no",
    "DOOR NO.": "door_no",
    "DOOR #": "door_no",
    "DOOR NUMBER": "door_no",
    "OPENING": "door_no",
    "OPENING NUMBER": "door_no",
    "ROOM NAME NUMBER": "door_no",
    "TO: ROOM": "door_no",
    "TO ROOM": "door_no",
    "ROOM": "door_no",
    "WIDTH": "width",
    "OPENING WIDTH": "width",
    "DOOR WIDTH": "width",
    "HEIGHT": "height",
    "OPENING HEIGHT": "height",
    "DOOR HEIGHT": "height",
    "DOOR MATERIAL": "door_material",
    "DOOR MAT'L": "door_material",
    "DOOR MATL": "door_material",
    "PANEL MATERIAL": "door_material",
    "PANEL MAT'L": "door_material",
    "PANEL MATL": "door_material",
    "MAT'L": "door_material",
    "MATL": "door_material",
    "MATERIAL": "door_material",
    "FRAME MATERIAL": "frame_material",
    "FRAME MAT'L": "frame_material",
    "FRAME MATL": "frame_material",
    "FRAME TYPE": "frame_material",
    "RATING": "fire_rating",
    "FIRE RATING": "fire_rating",
    "LIFE SAFETY FIRE RATING": "fire_rating",
    "HARDWARE": "hardware_set",
    "HARDWARE SET": "hardware_set",
    "HDW": "hardware_set",
    "HDW GROUP": "hardware_set",
    "HDW SET": "hardware_set",
    "SET": "hardware_set",
}

SCHEDULE_TITLE_RE = re.compile(
    r"(?:"
    r"DOOR\s+SCHEDULE"
    r"|OPENING\s+SCHEDULE\s*-\s*(?:COMMERCIAL|DETENTION)"
    r"|(?:UNIT|COMMON)\s+DOOR(?:\s+SCHEDULE)?"
    r"|(?:GUESTROOM|(?:\d+(?:ST|ND|RD|TH)\s+FLOOR\s+-\s+)?HOTEL)\s+DOOR\s+SCHEDULE"
    r")",
    re.IGNORECASE,
)

NON_DOOR_SUB_SCHEDULE_RE = re.compile(
    r"(?:SITE\s+GATE|STOREFRONT|WINDOW\s+SCHEDULE|DOOR\s+TYPES|DOOR\s+SCHEDULE\s+NOTES|"
    r"PARTITION\s+CONSTRUCTION|EXTERIOR\s+STOREFRONT|FENESTRATION)",
    re.IGNORECASE,
)

HEADER_HINTS = frozenset(
    {
        "MARK",
        "NUMBER",
        "DOOR",
        "OPENING",
        "WIDTH",
        "HEIGHT",
        "RATING",
        "HARDWARE",
        "HDW",
        "MATERIAL",
        "MAT'L",
        "MATL",
        "FRAME",
        "REMARKS",
        "DESCRIPTION",
        "TYPE",
        "ELEV",
        "THICK",
        "THICKNESS",
        "SET",
        "ROOM",
        "FROM",
        "TO",
        "GLAZING",
        "FINISH",
        "SIZE",
        "COMMENTS",
        "GROUP",
    }
)


def normalize_label(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip().upper())


def synonym_for_label(label: str) -> str | None:
    norm = normalize_label(label)
    if norm in SYNONYMS:
        return SYNONYMS[norm]
    # Prefer longest synonym keys to avoid REMARKS matching ROOM.
    for key in sorted(SYNONYMS, key=len, reverse=True):
        if norm == key or norm.endswith(" " + key) or norm.startswith(key + " "):
            return SYNONYMS[key]
    return None
