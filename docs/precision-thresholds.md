# Precision thresholds

ADR-0009's amendment committed to flipping `spec-check`'s `--mode` default from `preview` to `emit` only after measured FP/FN against the test corpus cleared empirical thresholds set "after at least three test projects are scored." This document is the home for that measurement methodology and the dated snapshots that come out of it.

**Status (2026-05-21):** Default remains `preview` for both `spec-check` and `drawing-index-qc`. The flip is deferred — see "Default-flip status" at the bottom.

This document originally covered only `spec-check`. As of 2026-05-21 (#19) it is the joint home for `drawing-index-qc` precision/recall too. Methodology below is shared; per-skill match-key tables and measurements live in their own subsections.

## Methodology

### Definitions

- **FP (false positive):** a finding the indexer produces that either
  - (i) matches no entry in the project's `expected.json`, **or**
  - (ii) matches an entry with `expected_action = suppress`.

  Both signal precision loss. `suppress` re-emissions are kept in the FP count rather than ignored, because the whole point of a `suppress` entry is "if the indexer produces this, the parser is broken." Quietly excluding them would hide a real bug class.

- **FN (false negative):** an entry in `expected.json` with `expected_action = emit_markup` that the indexer does not produce.

- **`info_only` entries** (e.g. Kadlec's 220 `broken_related_ref_div01` rollups): a produced finding that matches one is **not** a FP; a missing one is **not** a FN. They're real detections the deliverable aggregates rather than markups individually.

### Match key

Identity within a project, used to match produced rows against `expected.json` entries:

| Kind                                  | Match key                          |
|---------------------------------------|------------------------------------|
| `body_not_in_toc`                     | `(kind, section)`                  |
| `toc_not_in_body`                     | `(kind, section)`                  |
| `broken_related_ref`                  | `(kind, from_section, to_section)` |
| `broken_related_ref_div01`            | `(kind, from_section, to_section)` |
| `division_referenced_but_not_included`| `(kind, division)`                 |

**Page number is intentionally not part of the match key.** Section numbers are already unique within a project, and `(from, to)` ref pairs are unique in practice. Including page exposed pagination drift between `expected.json` (page numbers from legacy `.xlsx` reports during curation) and indexer-produced pages — drift that isn't a real precision problem. Page numbers remain on each finding as markup metadata; they're just not part of identity for FP/FN scoring.

#### Drawing-index match key

| Kind                          | Match key                              |
|-------------------------------|----------------------------------------|
| `sheet_in_index_not_in_set`   | `(kind, normalized_sheet_number)`      |
| `sheet_in_set_not_in_index`   | `(kind, normalized_sheet_number)`      |
| `sheet_number_mismatch`       | `(kind, normalized_sheet_number)`      |
| `duplicate_sheet_number`      | `(kind, normalized_sheet_number)`      |

`normalize_sheet_number` (qc_core/drawing/parse.py) collapses hyphens and case so `LS-101` and `LS101` share identity. Volume label and page are not part of the key — same drift rationale as spec-check (volume names vary between curated fixtures and parser output; pages can shift). The `notes` field is informational metadata (e.g. `master_index` vs `volume_index`), not identity.

### `unscored_kinds` carve-out

A project's `expected.json` may declare `"unscored_kinds": [...]` (top-level or inside `meta`). Findings of those kinds are excluded from both FP and FN on that project. Use this when ground truth doesn't cover a finding kind on a particular project — better than fabricating expected entries or silently inflating FP.

Currently no project uses this. (Quarry Oaks was a candidate for `broken_related_ref` since Tyler didn't review broken refs in the original engagement, but #13 curated them via interactive triage instead.)

### Reproducibility

```
python scripts/measure_precision.py            # spec-check
python scripts/measure_drawing_precision.py    # drawing-index-qc
```

Both scripts skip any project whose local path isn't configured (via `tests/local_paths.py` or env var). Each indexes the available projects into a tmpdir and reports per-project + cumulative numbers — FP/FN for spec-check, plus TP and per-kind precision/recall for drawing-index.

## Measurements

### 2026-05-20

| Project                  | Expected emit | Produced | FP | FN |
|--------------------------|--------------:|---------:|---:|---:|
| kadlec-lab               | 59            | 279      |  0 |  0 |
| juvenile-correctional    | 40            | 41       |  1 |  0 |
| quarry-oaks              | 33            | 34       |  1 |  0 |
| **Cumulative**           | **132**       | **354**  |  **2** |  **0** |
| **Cumulative %**         |               |          | **0.6%** | **0.0%** |

FP details:

- **juvenile-correctional:** `broken_related_ref 31 23 16.16 -> 02 41 13` — over-detection not in `expected.json`. Real FP, kept in the corpus as a known gap for indexer follow-up.
- **quarry-oaks:** `body_not_in_toc 31 20 00` — parser bug, the indexer misread a broken-ref mention of `31 20 00` as a section header. Marked `suppress` in `expected.json` so the bug stays visible until fixed.

FN: none.

(The "Produced" column dwarfs "Expected emit" because Kadlec contributes 220 `broken_related_ref_div01` rollups — `info_only` detections that the deliverable aggregates into one `division_referenced_but_not_included` markup rather than emitting individually.)

## Drawing-index measurements

### 2026-05-21 (baseline, #19)

| Project                     | ExpEmit | Produced | TP | FP | FN |
|-----------------------------|--------:|---------:|---:|---:|---:|
| kadlec-lab                  | 0       | 1        | 0  | 0  | 0  |
| quarry-oaks                 | 0       | 0        | 0  | 0  | 0  |
| embassy-suites-clearwater   | 17      | 17       | 17 | 0  | 0  |
| **Cumulative**              | **17**  | **18**   | **17** | **0** | **0** |
| **Cumulative %**            |         |          |    | **P=100.0%** | **R=100.0%** |

(Kadlec's single produced finding is the `LS-101` cross-discipline pair, curated as `info_only` — real detection, not scored as TP/FP.)

Per kind (across projects):

| Kind                          | TP | FP | FN | Precision | Recall |
|-------------------------------|---:|---:|---:|----------:|-------:|
| `sheet_in_index_not_in_set`   |  7 |  0 |  0 |   100.0%  | 100.0% |
| `sheet_in_set_not_in_index`   | 10 |  0 |  0 |   100.0%  | 100.0% |
| `sheet_number_mismatch`       |  0 |  0 |  0 |       n/a |   n/a  |
| `duplicate_sheet_number`      |  0 |  0 |  0 |       n/a |   n/a  |

FP: none. FN: none.

Note: the first measurement run on 2026-05-21 showed P=65.4% with 9 Kadlec FPs from area-suffix sheets (`AD101.A`, `A-111.B`, etc.). Root cause was a regex gap in [qc_core/drawing/parse.py](../qc_core/drawing/parse.py) — `_LINE_SHEET_RE` only accepted `.<digits>` after the sheet number, not `.<letters>`, so the index parser silently dropped every area-suffixed row. Extending the regex to `(?:\.[A-Za-z0-9]+)?` fixed it; Kadlec's 9 `suppress` entries became no-ops (still in `expected.json` as historical record of the parser gap). Numbers above reflect the post-fix state.

Per-kind action when below threshold:

- All kinds with data on the current corpus clear any reasonable threshold (100/100).
- `sheet_number_mismatch` and `duplicate_sheet_number` have no scored data. The corpus is silent rather than passing — re-baseline once a project exercises them (titleblock-calibrated set for mismatch; a same-discipline duplicate for dup-sheet, since the only existing duplicate is Kadlec's cross-discipline `LS-101` which is `info_only`).

## Known modeling gaps

These don't show up in the FP/FN table because the curation matched them, but they're worth carrying forward when the next precision measurement happens:

- ~~**AVW section-number near-miss splitting.**~~ *Resolved by #44.* A human-perceived AVW like Quarry Oaks' `10 28 13 (TOC) / 10 28 00 (body)` previously surfaced as two separate findings (`toc_not_in_body` + `body_not_in_toc`). The `section_number_mismatch` kind now fuses any TOC-only / body-only orphan pair sharing a normalized title into one finding ("Section number 10 28 00 should be 10 28 13").

- **Broken-ref mentions misread as body sections.** Quarry Oaks' `31 20 00` "Earth Moving" came from this — the body extractor picked up an in-text mention of a referenced section number and treated it as a section header. Kadlec has a different class of the same kind of bug (TOC running-header artifacts, also documented in its `expected.json` as `suppress`). Worth investigating whether the body-section detector can use surrounding-line layout signals to filter these.

- **(Resolved 2026-05-21)** Architectural area-suffix splits treated as un-indexed sheets. The original symptom on Kadlec — `AD101.A/.B`, `A-111.B`, `A-120.B`, `A-151.A/.B` firing `sheet_in_set_not_in_index` — turned out to be two stacked bugs: (1) `_LINE_SHEET_RE` rejected `.<letter>` suffixes so the index parser never read those rows; (2) when the index DID list only a base sheet, the cross-check didn't treat `<base>.<suffix>` in the set as covered. Both fixed in the regex + a new `_index_covers` helper in [qc_core/drawing/indexer.py](../qc_core/drawing/indexer.py).

## Default-flip status

**Default remains `--mode=preview` for both `spec-check` and `drawing-index-qc`.**

### spec-check

The original commitment in ADR-0009 was to flip once the corpus cleared thresholds. The 2026-05-20 measurement easily clears any reasonable threshold (cumulative FP 0.6%, FN 0%), but the flip is deferred for a different reason: **on the current product, the flip is cosmetic.**

- Tyler is the only Reviewer.
- `--mode=emit` is one flag away whenever Tyler wants markups.
- ADR-0009's contamination concern is mitigated by the Author filter — any rejected Candidate is one bulk-delete away.
- Threshold numbers picked from a 3-project corpus would be re-litigated the moment a 4th project lands or a second MCP-writing check ships.

### drawing-index-qc (added 2026-05-21, #19)

Same product reasoning as spec-check above — single Reviewer, `--mode=emit` is one flag away, threshold numbers from a 3-project corpus would be re-litigated as soon as a 4th project lands. After the 2026-05-21 indexer fix, both kinds with data on the current corpus measure at 100/100, so there is no precision blocker; the flip remains deferred only for the product-shape reason, not for a data reason.

### Revisit trigger (applies to both)

Revisit the flip when **any** of the following holds:

1. A second MCP-writing check (door-schedule, RCP coordination, etc.) ships and standardizing one default across checks would simplify the Reviewer's workflow.
2. The Reviewer wants `emit` as the default to stop typing `--mode=emit` per run.

When that revisit happens, the methodology in this document is the load-bearing piece. The 2026-05-20 spec-check measurement and the 2026-05-21 drawing-index measurement are the baselines; any regression between then and the revisit is the signal to investigate before changing the default.
