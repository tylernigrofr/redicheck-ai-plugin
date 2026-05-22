"""Project-generalizable spec-check knobs (ADR-0005)."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DivisionRollupConfig:
    """
    When a division has no body sections but many broken refs, emit one summary finding.

    rollup_emit_exceptions: broken refs to these targets stay emit_markup even when
    their division is rolled up (Kadlec-validated rare Div01 sections in expected.json).
    """

    min_broken_refs: int = 20
    comment_template: str = (
        "Many Division {division} sections referenced across specification, "
        "CNL any Division {division} sections"
    )
    rollup_emit_exceptions: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {"01 21 00", "01 51 00", "01 57 19", "01 91 00"}
        )
    )


DEFAULT_DIVISION_ROLLUP = DivisionRollupConfig()
