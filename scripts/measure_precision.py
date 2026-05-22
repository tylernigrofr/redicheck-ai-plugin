"""Measure spec-check FP/FN against the test-corpus ground truth.

Usage:
    python scripts/measure_precision.py

Reads expected.json + indexes each test project (Kadlec, Juvenile, Quarry Oaks)
that has its local path configured, then computes per-project and cumulative
FP/FN per the methodology in docs/precision-thresholds.md.

Match keys:
  - body_not_in_toc / toc_not_in_body: (kind, section, page)
  - broken_related_ref: (kind, from_anchor, to_section, source_page)
  - division_referenced_but_not_included: (kind, division)
  - broken_related_ref_div01: (kind, from_anchor, to_section, source_page)

FP = produced finding either (i) not matching any expected.json entry, or
     (ii) matching a `suppress` entry.
FN = expected.json entry with expected_action='emit_markup' not produced by
     the indexer.

`unscored_kinds` declared in an expected.json carves those kinds out of both
FP and FN scoring for that project.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from qc_core.db import init_db  # noqa: E402
from qc_core.spec.indexer import index_project  # noqa: E402

# Reuse the conftest path-resolution helpers so local_paths.py / env vars work.
sys.path.insert(0, str(REPO_ROOT / "tests"))
try:
    import local_paths as _local_paths  # type: ignore
except ImportError:
    _local_paths = None

import os


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
        "pdf_glob": "Specs.pdf",
    },
    {
        "slug": "juvenile-correctional",
        "local_attr": "JUVENILE_PATH",
        "env_var": "REDICHECK_JUVENILE_PATH",
        "pdf_glob": "Specs*.pdf",
    },
    {
        "slug": "quarry-oaks",
        "local_attr": "QUARRY_OAKS_PATH",
        "env_var": "REDICHECK_QUARRY_OAKS_PATH",
        "pdf_glob": "*Specs*.pdf",
    },
]


def _produced_key(row: dict) -> tuple:
    kind = row["kind"]
    if kind in ("body_not_in_toc", "toc_not_in_body"):
        return (kind, row.get("section"))
    if kind in ("broken_related_ref", "broken_related_ref_div01"):
        anchor = row.get("from_section") or row.get("from_label")
        return (kind, anchor, row.get("to_section"))
    if kind == "division_referenced_but_not_included":
        return (kind, row.get("division"))
    return (kind,)


def _expected_key(exp: dict) -> tuple:
    kind = exp["kind"]
    if kind in ("body_not_in_toc", "toc_not_in_body"):
        return (kind, exp.get("section"))
    if kind in ("broken_related_ref", "broken_related_ref_div01"):
        anchor = exp.get("from_section") or exp.get("from_label")
        return (kind, anchor, exp.get("to_section"))
    if kind == "division_referenced_but_not_included":
        return (kind, exp.get("division"))
    return (kind,)


def measure_project(slug: str, project_dir: Path, pdf_glob: str, expected: dict) -> dict:
    work = project_dir
    # Index into a tmp copy so we don't write back to the user's folder.
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix=f"measure-{slug}-"))
    try:
        for pdf in project_dir.glob(pdf_glob):
            shutil.copy2(pdf, tmp / pdf.name)
        index_project(tmp, force=True)
        conn = init_db(tmp / "qc.sqlite")
        produced = [
            dict(r)
            for r in conn.execute(
                """
                SELECT kind, section, body_page, toc_page, from_section, from_label,
                       to_section, source_page, division
                FROM findings
                """
            ).fetchall()
        ]
        conn.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    unscored = set(expected.get("meta", {}).get("unscored_kinds", []))
    unscored |= set(expected.get("unscored_kinds", []))

    # Build expected lookup by key, keeping the expected_action.
    expected_index: dict[tuple, str] = {}
    for f in expected["findings"]:
        if f["kind"] in unscored:
            continue
        expected_index[_expected_key(f)] = f["expected_action"]

    produced_keys: list[tuple] = []
    for r in produced:
        if r["kind"] in unscored:
            continue
        produced_keys.append(_produced_key(r))

    fp_kinds: dict[str, int] = {}
    fn_kinds: dict[str, int] = {}
    fp_details: list[tuple] = []
    fn_details: list[tuple] = []

    produced_set = set(produced_keys)
    for key in produced_keys:
        action = expected_index.get(key)
        if action is None or action == "suppress":
            fp_kinds[key[0]] = fp_kinds.get(key[0], 0) + 1
            fp_details.append(key)

    for key, action in expected_index.items():
        if action != "emit_markup":
            continue
        if key not in produced_set:
            fn_kinds[key[0]] = fn_kinds.get(key[0], 0) + 1
            fn_details.append(key)

    expected_emit_count = sum(
        1 for a in expected_index.values() if a == "emit_markup"
    )
    produced_scored_count = len(produced_keys)

    return {
        "slug": slug,
        "expected_emit": expected_emit_count,
        "produced": produced_scored_count,
        "fp": sum(fp_kinds.values()),
        "fn": sum(fn_kinds.values()),
        "fp_by_kind": fp_kinds,
        "fn_by_kind": fn_kinds,
        "fp_details": fp_details,
        "fn_details": fn_details,
        "unscored_kinds": sorted(unscored),
    }


def main() -> int:
    results = []
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
        results.append(measure_project(proj["slug"], project_dir, proj["pdf_glob"], expected))

    if not results:
        print("No projects measured.")
        return 1

    print("\n" + "=" * 78)
    print(f"{'Project':<28} {'ExpEmit':>8} {'Produced':>9} {'FP':>5} {'FN':>5}  Notes")
    print("-" * 78)
    cum_exp = cum_prod = cum_fp = cum_fn = 0
    for r in results:
        cum_exp += r["expected_emit"]
        cum_prod += r["produced"]
        cum_fp += r["fp"]
        cum_fn += r["fn"]
        notes = ""
        if r["unscored_kinds"]:
            notes = f"unscored: {','.join(r['unscored_kinds'])}"
        print(
            f"{r['slug']:<28} {r['expected_emit']:>8} {r['produced']:>9} {r['fp']:>5} {r['fn']:>5}  {notes}"
        )
    print("-" * 78)
    fp_pct = (cum_fp / cum_prod * 100) if cum_prod else 0
    fn_pct = (cum_fn / cum_exp * 100) if cum_exp else 0
    print(
        f"{'CUMULATIVE':<28} {cum_exp:>8} {cum_prod:>9} {cum_fp:>5} {cum_fn:>5}  "
        f"FP={fp_pct:.1f}% FN={fn_pct:.1f}%"
    )
    print()

    for r in results:
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
