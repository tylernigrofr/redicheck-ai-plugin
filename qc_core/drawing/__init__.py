"""Drawing index indexing and query layer (ADR-0010)."""

from qc_core.drawing.kinds import DRAWING_FINDING_KINDS
from qc_core.drawing.indexer import index_project, needs_reindex
from qc_core.drawing.queries import (
    all_findings,
    findings_by_kind,
    query_duplicate_sheet_number,
    query_sheet_in_index_not_in_set,
    query_sheet_in_set_not_in_index,
    query_sheet_number_mismatch,
)

__all__ = [
    "DRAWING_FINDING_KINDS",
    "all_findings",
    "findings_by_kind",
    "index_project",
    "needs_reindex",
    "query_duplicate_sheet_number",
    "query_sheet_in_index_not_in_set",
    "query_sheet_in_set_not_in_index",
    "query_sheet_number_mismatch",
]
