"""Per-project column mapping persistence and synonym resolution."""

from __future__ import annotations

import sqlite3

from qc_core.door.synonyms import CANONICAL_FIELDS, normalize_label, synonym_for_label


def load_column_mappings(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        "SELECT raw_label, canonical_field FROM door_column_mappings"
    ).fetchall()
    mapping = {normalize_label(r["raw_label"]): r["canonical_field"] for r in rows}
    for label, field in mapping.items():
        mapping.setdefault(label, field)
    return mapping


def save_column_mapping(
    conn: sqlite3.Connection, raw_label: str, canonical_field: str
) -> None:
    if canonical_field not in CANONICAL_FIELDS:
        raise ValueError(f"Unknown canonical field: {canonical_field}")
    conn.execute(
        """
        INSERT OR REPLACE INTO door_column_mappings (raw_label, canonical_field)
        VALUES (?, ?)
        """,
        (raw_label.strip(), canonical_field),
    )


def resolve_column_map(
    conn: sqlite3.Connection, raw_labels: list[str]
) -> tuple[dict[str, str], list[str]]:
    """Return label->canonical map and unfamiliar labels needing Reviewer input."""
    persisted = load_column_mappings(conn)
    resolved: dict[str, str] = {}
    unfamiliar: list[str] = []
    for label in raw_labels:
        norm = normalize_label(label)
        if norm in persisted:
            resolved[label] = persisted[norm]
            continue
        syn = synonym_for_label(label)
        if syn:
            resolved[label] = syn
            continue
        unfamiliar.append(label)
    return resolved, unfamiliar


def apply_canonical_row(
    raw: dict[str, str], column_map: dict[str, str]
) -> tuple[dict[str, str | None], dict[str, str]]:
    canonical = {f: None for f in CANONICAL_FIELDS}
    attributes: dict[str, str] = {}
    for raw_label, value in raw.items():
        if not value:
            continue
        field = column_map.get(raw_label)
        if field and field in canonical and canonical[field] is None:
            canonical[field] = value
        elif field and field in canonical and canonical[field] is not None:
            attributes[raw_label] = value
        else:
            attributes[raw_label] = value
    return canonical, attributes
