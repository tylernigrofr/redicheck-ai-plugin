"""CLI: foodservice utility schedule vs electrical kitchen equipment schedule.

    python -m qc_core.foodservice.cli "<project folder>"
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from qc_core.discovery import qc_sqlite_path
from qc_core.db import init_db
from qc_core.foodservice.indexer import index_foodservice_electrical
from qc_core.foodservice.kinds import FS_ELEC_FINDING_KINDS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cross-check foodservice utility schedules against the "
        "electrical kitchen equipment schedule."
    )
    parser.add_argument("project_folder", help="Folder containing the drawing PDFs")
    args = parser.parse_args(argv)

    root = Path(args.project_folder)
    if not root.is_dir():
        print(f"error: not a folder: {root}", file=sys.stderr)
        return 2

    result = index_foodservice_electrical(root)
    print(f"=== foodservice-vs-electrical ({root.name}) ===")
    print(f"FS utility schedule sheets: {len(result.fs_pages)} "
          f"({', '.join(result.fs_pages)})")
    print(f"Electrical kitchen schedule sheets: {', '.join(result.elec_pages) or '(none)'}")
    print(f"FS items extracted: {result.fs_items}   "
          f"Electrical marks extracted: {result.elec_marks}")
    print(f"Total findings: {result.findings}\n")

    conn = init_db(qc_sqlite_path(root))
    try:
        placeholders = ",".join("?" * len(FS_ELEC_FINDING_KINDS))
        rows = conn.execute(
            f"""SELECT kind, severity, sheet_number, title, notes
                FROM findings WHERE kind IN ({placeholders})
                ORDER BY kind, title""",
            FS_ELEC_FINDING_KINDS,
        ).fetchall()
    finally:
        conn.close()

    by_kind: dict[str, list] = defaultdict(list)
    for r in rows:
        by_kind[r["kind"]].append(r)

    for kind in FS_ELEC_FINDING_KINDS:
        group = by_kind.get(kind, [])
        if not group:
            continue
        print(f"## {kind} ({len(group)})")
        for r in group:
            sheet = f"{r['sheet_number']} " if r["sheet_number"] else ""
            print(f"  [{r['severity']}] {sheet}{r['title'] or ''} — {r['notes']}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
