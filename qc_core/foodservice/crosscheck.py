"""Cross-check foodservice utility items against electrical kitchen marks.

Pure comparison logic over extracted ``FsItem`` / ``ElecMark`` records, so it is
unit-testable without PyMuPDF or SQLite. The indexer persists the inputs and
turns the returned finding dicts into rows in the ``findings`` table.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from qc_core.foodservice.extract import ElecMark, FsItem

# An electrical mark equals an FS item number plus an optional unit suffix:
# ".N" (A6.1), a letter (A1a), or both (A6.1a). Used to resolve a mark to its
# parent FS item by longest valid prefix.
_SUFFIX_RE = re.compile(r"^(?:\.\d{1,2})?[a-z]?$")
_TRAILING_LETTER_RE = re.compile(r"[a-z]$")


def _num(value: str | None) -> float | None:
    if not value:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
    return float(m.group()) if m else None


def resolve_fs_item(mark: str, fs_numbers: list[str]) -> str | None:
    """Longest FS item number that is a valid prefix of ``mark``.

    FS sub-items map 1:1 (elec C1.1 -> FS C1.1 when it exists); otherwise a mark
    rolls up to its base (elec A6.1 -> FS A6; elec A1a -> FS A1).
    """
    best: str | None = None
    for num in fs_numbers:
        if mark == num or (mark.startswith(num) and _SUFFIX_RE.match(mark[len(num):])):
            if best is None or len(num) > len(best):
                best = num
    return best


def _unit_id(mark: str) -> str:
    """A unit instance: drop a trailing connection letter (A1a/A1b -> A1)."""
    return _TRAILING_LETTER_RE.sub("", mark)


# Nominal single-phase voltage classes: the foodservice consultant often lists
# nameplate voltage (115V) where electrical lists the nominal service (120V).
# These are electrically equivalent and flagged separately, not as a hard error.
_VOLTAGE_CLASSES = ({110.0, 115.0, 120.0, 125.0}, {220.0, 230.0, 240.0})


def _same_voltage_class(a: float, b: float) -> bool:
    return any(a in cls and b in cls for cls in _VOLTAGE_CLASSES)


def _fs_conn_norm(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().upper()
    if "DIRECT" in v:
        return "hardwired"
    if "PLUG" in v:
        return "receptacle"
    return v.lower()


def _height_norm(value: str | None) -> str | None:
    if not value:
        return None
    v = value.upper()
    note = re.search(r"NOTE.*?\((\d+)\)|\((\d+)\).*?NOTE", v)
    if note:
        return f"NOTE{note.group(1) or note.group(2)}"
    digits = re.sub(r'[^0-9./-]', "", v)
    return digits or None


@dataclass
class FieldResult:
    field: str
    fs_value: str | None
    elec_values: list[str]
    ok: bool
    nominal: bool = False  # True when only a nominal-voltage variance (115 vs 120)


def _compare_field(field: str, it: FsItem, marks: list[ElecMark]) -> FieldResult | None:
    """The FS value must appear among the marks' values for that field. Returns
    None when there is nothing to compare (FS value absent)."""
    if field == "volts":
        fs_v = _num(it.volts)
        if fs_v is None:
            return None
        elec_nums = [n for n in (_num(m.volt) for m in marks) if n is not None]
        if any(abs(fs_v - n) < 0.05 for n in elec_nums):
            return FieldResult("volts", it.volts, [m.volt or "" for m in marks], True)
        nominal = any(_same_voltage_class(fs_v, n) for n in elec_nums)
        return FieldResult("volts", it.volts, [m.volt or "" for m in marks],
                           ok=False, nominal=nominal)

    if field == "amps":
        fs_v = _num(it.amps)
        if fs_v is None:
            return None
        elec_nums = [n for n in (_num(m.amps) for m in marks) if n is not None]
        ok = any(abs(fs_v - n) < 0.05 for n in elec_nums)
        # one unit split across connections: FS may list the summed amperage
        if not ok and len({_unit_id(m.mark) for m in marks}) == 1 and len(elec_nums) > 1:
            ok = abs(fs_v - sum(elec_nums)) < 0.1
        return FieldResult("amps", it.amps, [m.amps or "" for m in marks], ok)

    if field == "kw":
        fs_v = _num(it.kw)
        if fs_v is None:
            return None
        elec_nums = [n for n in (_num(m.watts) for m in marks) if n is not None]
        ok = any(abs(fs_v * 1000 - w) <= 1.0 for w in elec_nums)
        return FieldResult("kw/watts", it.kw, [m.watts or "" for m in marks], ok)

    if field == "elec_conn_type":
        fs_v = _fs_conn_norm(it.elec_conn_type)
        if fs_v is None:
            return None
        elec_vals = [m.connection for m in marks if m.connection]
        return FieldResult("conn", it.elec_conn_type, elec_vals, fs_v in elec_vals)

    if field == "elec_rough_in_aff":
        fs_v = _height_norm(it.elec_rough_in_aff)
        if fs_v is None:
            return None
        elec_vals = [_height_norm(m.height) for m in marks]
        return FieldResult("height", it.elec_rough_in_aff,
                           [m.height or "" for m in marks], fs_v in elec_vals)

    # phase
    fs_v = _num(it.ph)
    if fs_v is None:
        return None
    elec_nums = [n for n in (_num(m.phase) for m in marks) if n is not None]
    ok = any(abs(fs_v - n) < 0.05 for n in elec_nums)
    return FieldResult("phase", it.ph, [m.phase or "" for m in marks], ok)


def _has_elec_data(it: FsItem) -> bool:
    return any(v not in (None, "", "0") for v in (it.volts, it.amps, it.kw))


def crosscheck(fs_items: list[FsItem], elec_marks: list[ElecMark]) -> list[dict]:
    """Return finding dicts comparing the two schedules in both directions."""
    fs_by_num: dict[str, FsItem] = {}
    for it in fs_items:
        # If an item number appears on multiple sheets, keep the one with data.
        if it.item_number not in fs_by_num or _has_elec_data(it):
            fs_by_num[it.item_number] = it
    fs_numbers = list(fs_by_num)

    groups: dict[str, list[ElecMark]] = defaultdict(list)
    unresolved: list[ElecMark] = []
    for m in elec_marks:
        base = resolve_fs_item(m.mark, fs_numbers)
        (groups[base].append(m) if base else unresolved.append(m))

    findings: list[dict] = []

    for num, it in fs_by_num.items():
        marks = groups.get(num, [])
        if not marks:
            if _has_elec_data(it):
                findings.append({
                    "kind": "fs_item_missing_in_electrical",
                    "item": num, "sheet": it.bbox and num,
                    "source_sheet": getattr(it, "source_sheet", None),
                    "note": (f"FS item {num} ({it.description or ''}) has electrical "
                             f"data (V={it.volts} A={it.amps} KW={it.kw}) but no "
                             f"matching MARK on the electrical schedule"),
                })
            continue

        if not _has_elec_data(it):
            findings.append({
                "kind": "fs_item_no_elec_data",
                "item": num, "marks": [m.mark for m in marks],
                "note": (f"electrical schedule has mark(s) "
                         f"{', '.join(m.mark for m in marks)} for FS item {num} "
                         f"but the FS row shows no electrical requirements"),
            })
            continue

        units = len({_unit_id(m.mark) for m in marks})
        if it.qty and it.qty.isdigit() and int(it.qty) != units:
            findings.append({
                "kind": "fs_elec_qty_mismatch",
                "item": num, "fs_qty": it.qty, "elec_units": units,
                "marks": [m.mark for m in marks],
                "note": (f"FS QTY={it.qty} but electrical shows {units} unit(s): "
                         f"{', '.join(m.mark for m in marks)}"),
            })

        for field in ("volts", "phase", "amps", "kw", "elec_conn_type", "elec_rough_in_aff"):
            res = _compare_field(field, it, marks)
            if res and not res.ok:
                findings.append({
                    "kind": "fs_elec_nominal_voltage_variance" if res.nominal
                            else "fs_elec_field_mismatch",
                    "item": num, "field": res.field,
                    "fs_value": res.fs_value,
                    "elec_values": res.elec_values,
                    "marks": [m.mark for m in marks],
                    "note": (f"{res.field}: FS={res.fs_value!r} vs electrical "
                             f"{res.elec_values} (marks {', '.join(m.mark for m in marks)})"),
                })

    for m in unresolved:
        findings.append({
            "kind": "elec_mark_missing_in_fs",
            "mark": m.mark,
            "note": (f"electrical MARK {m.mark} ({m.description or ''}) has no "
                     f"matching item number on any FS utility schedule"),
        })

    return findings
