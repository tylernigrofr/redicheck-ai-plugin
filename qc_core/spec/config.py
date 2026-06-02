"""Project-generalizable spec-check knobs (ADR-0005)."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EmbeddedReportConfig:
    """Recognize embedded non-CSI documents bound into a spec set (#43).

    Reports like a Geotechnical Engineering Report are listed in the spec TOC
    (often at a sub-decimal number under a data section, e.g. ``00 31 32.01``)
    but have no ``SECTION NN NN NN`` CSI body header, so the TOC↔body diff would
    otherwise flag them as a false ``toc_not_in_body``. When the PDF outline
    confirms the document is actually bound in (a bookmark for the number whose
    subtree carries its own Table of Contents), we downgrade the finding to an
    informational ``embedded_report_present`` note instead.

    title_keywords: case-insensitive substrings marking a TOC title as a likely
    embedded report (kept a knob so surveys / environmental / abatement reports
    generalize beyond geotechnical).
    """

    title_keywords: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "report",
                "geotechnical",
                "survey",
                "addendum",
                "environmental",
                "abatement",
                "study",
                "investigation",
            }
        )
    )


DEFAULT_EMBEDDED_REPORT = EmbeddedReportConfig()


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
