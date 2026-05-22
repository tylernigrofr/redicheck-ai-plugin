"""Measure drawing-index-qc FP/FN against the test-corpus ground truth.

Usage:
    python scripts/measure_drawing_precision.py

Parallel to scripts/measure_precision.py (#8) but for drawing-index findings
across Kadlec, Quarry Oaks, and Embassy Suites Clearwater. Computes per-kind
precision/recall per project plus aggregate.

Match key: (kind, normalized_sheet_number). Page numbers and volume labels are
not part of identity — same rationale as spec-check (curated pages drift vs
parser output; sheet numbers are unique within a project per kind).

FP = produced finding either (i) not matching any expected.json entry, or
     (ii) matching a `suppress` entry. `info_only` matches are neither FP nor
     FN (real detection that ground truth excludes from emit).
FN = expected.json entry with expected_action='emit_markup' not produced.

`unscored_kinds` in drawing_index carves those kinds out of both FP and FN.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from qc_core.db import init_db  # noqa: E402
from qc_core.drawing.indexer import index_project  # noqa: E402
from qc_core.drawing.kinds import DRAWING_FINDING_KINDS  # noqa: E402
from qc_core.drawing.parse import normalize_sheet_number  # noqa: E402

try:
    import local_paths as _local_paths  # type: ignore
except ImportError:
    _local_paths = None


def _resolve(local_attr: str, env_var: str) -> str | None:
    if _local_paths is not None:
        val = getattr(_local_paths, local_attr, None)
        if val:
            return val
    return os.environ.get(env_var)


PROJECTS = [
    {
        "slug": "kadlec-lab",
        "local_attr": "KADLEC_LAB_PATH",
        "env_var": "REDICHECK_KADLEC_LAB_PATH",
        "drawing_glob": "Drawings.pdf",
    },
    {
        "slug": "quarry-oaks",
        "local_attr": "QUARRY_OAKS_PATH",
        "env_var": "REDICHECK_QUARRY_OAKS_PATH",
        "drawing_glob": "[0-9][0-9] *.pdf",
    },
    {
        "slug": "embassy-suites-clearwater",
        "local_attr": "EMBASSY_SUITES_CLEARWATER_PATH",
        "env_var": "REDICHECK_EMBASSY_SUITES_CLEARWATER_PATH",
        "drawing_glob": "[0-9][0-9]-*.pdf",
    },
]


def _key(kind: str, sheet_number: str) -> tuple:
    return (kind, normalize_sheet_number(sheet_number))


def measure_project(slug: str, project_dir: Path, drawing_glob: str, expected: dict) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix=f"measure-drawing-{slug}-"))
    try:
        copied = 0
        for pdf in project_dir.glob(drawing_glob):
            # Skip spec PDFs that match the glob accidentally (e.g. "10 Specs Vol 1.pdf"
            # under quarry-oaks). Drawing fixtures list their drawings in
            # source_pdfs.drawings; restrict to those when present.
            allowed = expected.get("source_pdfs", {}).get("drawings")
            if allowed is not None and pdf.name not in allowed:
                continue
            shutil.copy2(pdf, tmp / pdf.name)
            copied += 1
        if copied == 0:
            return {"slug": slug, "error": "no drawing PDFs copied"}
        index_project(tmp, force=True)
        conn = init_db(tmp / "qc.sqlite")
        placeholders = ",".join("?" * len(DRAWING_FINDING_KINDS))
        produced = [
            dict(r)
            for r in conn.execute(
                f"""
                SELECT kind, sheet_number, source_page, notes
                FROM findings
                WHERE kind IN ({placeholders})
                """,
                DRAWING_FINDING_KINDS,
            ).fetchall()
        ]
        conn.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    di = expected.get("drawing_index", {})
    unscored = set(di.get("unscored_kinds", []))
    expected_findings = di.get("findings", [])

    expected_index: dict[tuple, str] = {}
    for f in expected_findings:
        if f["kind"] in unscored:
            continue
        expected_index[_key(f["kind"], f["sheet_number"])] = f["expected_action"]

    produced_keys: list[tuple] = []
    produced_detail: dict[tuple, dict] = {}
    for r in produced:
        if r["kind"] in unscored:
            continue
        k = _key(r["kind"], r["sheet_number"])
        produced_keys.append(k)
        produced_detail.setdefault(k, r)

    fp_kinds: dict[str, int] = {}
    fn_kinds: dict[str, int] = {}
    fp_details: list[tuple] = []
    fn_details: list[tuple] = []
    tp_kinds: dict[str, int] = {}

    produced_set = set(produced_keys)
    counted: set[tuple] = set()
    for key in produced_keys:
        if key in counted:
            continue
        counted.add(key)
        action = expected_index.get(key)
        if action is None or action == "suppress":
            fp_kinds[key[0]] = fp_kinds.get(key[0], 0) + 1
            fp_details.append(key)
        elif action == "emit_markup":
            tp_kinds[key[0]] = tp_kinds.get(key[0], 0) + 1
        # info_only: real detection, neither FP nor TP for emit-precision.

    for key, action in expected_index.items():
        if action != "emit_markup":
            continue
        if key not in produced_set:
            fn_kinds[key[0]] = fn_kinds.get(key[0], 0) + 1
            fn_details.append(key)

    expected_emit_count = sum(1 for a in expected_index.values() if a == "emit_markup")
    produced_scored_count = len(set(produced_keys))

    return {
        "slug": slug,
        "expected_emit": expected_emit_count,
        "produced": produced_scored_count,
        "fp": sum(fp_kinds.values()),
        "fn": sum(fn_kinds.values()),
        "tp_by_kind": tp_kinds,
        "fp_by_kind": fp_kinds,
        "fn_by_kind": fn_kinds,
        "fp_details": fp_details,
        "fn_details": fn_details,
        "unscored_kinds": sorted(unscored),
    }


def main() -> int:
    results: list[dict] = []
    for proj in PROJECTS:
        raw = _resolve(proj["local_attr"], proj["env_var"])
        if not raw:
            print(f"SKIP {proj['slug']}: {proj['env_var']} unset")
            continue
        project_dir = Path(raw)
        if not project_dir.is_dir():
            print(f"SKIP {proj['slug']}: {project_dir} not a directory")
            continue
        expected_path = (
            REPO_ROOT / "tests" / "fixtures" / "projects" / proj["slug"] / "expected.json"
        )
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        print(f"Measuring {proj['slug']}...")
        results.append(
            measure_project(proj["slug"], project_dir, proj["drawing_glob"], expected)
        )

    if not results:
        print("No projects measured.")
        return 1

    print("\n" + "=" * 90)
    print(f"{'Project':<32} {'ExpEmit':>8} {'Produced':>9} {'TP':>5} {'FP':>5} {'FN':>5}  Notes")
    print("-" * 90)
    cum = {"exp": 0, "prod": 0, "fp": 0, "fn": 0, "tp": 0}
    for r in results:
        if "error" in r:
            print(f"{r['slug']:<32} ERROR: {r['error']}")
            continue
        tp = sum(r["tp_by_kind"].values())
        cum["exp"] += r["expected_emit"]
        cum["prod"] += r["produced"]
        cum["fp"] += r["fp"]
        cum["fn"] += r["fn"]
        cum["tp"] += tp
        notes = f"unscored: {','.join(r['unscored_kinds'])}" if r["unscored_kinds"] else ""
        print(
            f"{r['slug']:<32} {r['expected_emit']:>8} {r['produced']:>9} {tp:>5} {r['fp']:>5} {r['fn']:>5}  {notes}"
        )
    print("-" * 90)
    prec = (cum["tp"] / (cum["tp"] + cum["fp"]) * 100) if (cum["tp"] + cum["fp"]) else 0
    rec = (cum["tp"] / (cum["tp"] + cum["fn"]) * 100) if (cum["tp"] + cum["fn"]) else 0
    print(
        f"{'CUMULATIVE':<32} {cum['exp']:>8} {cum['prod']:>9} {cum['tp']:>5} {cum['fp']:>5} {cum['fn']:>5}  "
        f"P={prec:.1f}% R={rec:.1f}%"
    )

    # Per-kind breakdown across projects.
    print("\nPer-kind aggregate (TP / FP / FN, precision, recall):")
    agg: dict[str, dict[str, int]] = {}
    for r in results:
        if "error" in r:
            continue
        for k, v in r["tp_by_kind"].items():
            agg.setdefault(k, {"tp": 0, "fp": 0, "fn": 0})["tp"] += v
        for k, v in r["fp_by_kind"].items():
            agg.setdefault(k, {"tp": 0, "fp": 0, "fn": 0})["fp"] += v
        for k, v in r["fn_by_kind"].items():
            agg.setdefault(k, {"tp": 0, "fp": 0, "fn": 0})["fn"] += v
    for kind in sorted(agg):
        s = agg[kind]
        p = (s["tp"] / (s["tp"] + s["fp"]) * 100) if (s["tp"] + s["fp"]) else float("nan")
        rc = (s["tp"] / (s["tp"] + s["fn"]) * 100) if (s["tp"] + s["fn"]) else float("nan")
        print(f"  {kind:<32} TP={s['tp']:>3} FP={s['fp']:>3} FN={s['fn']:>3}  P={p:.1f}%  R={rc:.1f}%")

    for r in results:
        if "error" in r:
            continue
        if r["fp_details"]:
            print(f"\n{r['slug']} FP detail ({r['fp']}):")
            for k in r["fp_details"]:
                print(f"  {k}")
        if r["fn_details"]:
            print(f"\n{r['slug']} FN detail ({r['fn']}):")
            for k in r["fn_details"]:
                print(f"  {k}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
