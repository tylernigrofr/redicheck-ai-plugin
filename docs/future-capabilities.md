# Future capabilities (v1+ parking lot)

Things we've explicitly considered, decided are out of v0 scope, and want to revisit. Not a roadmap commitment — a memory aid so good ideas don't get re-relitigated from scratch later. Grouped by the layer they belong to (see ADR-0003).

## More extraction targets (after doors generalize)

- **Fixture / equipment schedules** — same pattern as doors. Lighting fixtures (RCP coordination), plumbing fixtures, mechanical equipment. Each gets its own Schedule type with hybrid schema.
- **Finish schedules** — rooms and their floor/wall/ceiling finishes. Cross-references to room numbers and spec sections.
- **Room/space Entities** — extract room numbers + names + areas from plan sheets. Unlocks the "show all doors in corridors" pattern (query (c)) and is itself a coordination layer.
- **Keynotes and general notes** — extract sheet-level keynote lists and link keynote callouts on plans back to their definitions.
- **Detail callouts** — `3/A6.21` style references on plans; resolve to the actual detail sheet.
- **Spec section indexing** — go beyond `legacy/spec-check`'s consistency checks: parse spec sections into structured records, link spec-section references in schedules/plans to their definitions.
- **Title block extraction across the whole set** — sheet metadata indexed once so queries like "what's the latest revision on sheet A2.01" become trivial.

## Door-check follow-ons (after bundled door-check ships per ADR-0022)

- **Primary-occurrence classification on door tags** — door-check v1 records every text-match of a `door_no` on every Architectural plan sheet without distinguishing the "primary" occurrence (the actual door tag on the floor plan) from secondary occurrences (door referenced in a section cut, RCP, callout, etc.). The primary-occurrence check is the AEC-correct framing: every door should have exactly one floor-plan tag, and secondary references should resolve back to it. Needed once Findings get sharper — e.g. "door on plan but tagged on a different floor's plan" requires knowing which plan is the primary. Likely combines text-layer position with the per-sheet discipline + sheet-number-prefix conventions (e.g. `A1xx` = floor plans, `A2xx` = sections/elevations).
- **Door Schedule ↔ Division 08 spec cross-reference (door-check v1.1)** — descoped from the initial bundled door-check. The Door Schedule's MAT'L, HARDWARE, and ACCESS CONTROL columns reference multiple Division 08 spec sections (08 11 13 Hollow Metal, 08 14 16/23 Wood, 08 34 73 Detention, 08 41 13 Aluminum, 08 71 00 Hardware, 08 71 13 Power Operators, plus detention variants 08 71 15 / 08 71 63). Two high-value Findings this unlocks: **hardware-set reference resolution** (schedule names a hardware set like `HW-7` or `D02`; 08 71 00 should define it — undefined → Finding) and **material-to-section coverage** (every door material in the schedule should have a corresponding Division 08 section — e.g. DHM doors with no 08 34 73 → Finding). Pure SQL joins between the `doors` and `spec_sections` tables — exactly the cross-document Findings shape the database-ification thesis (ADR-0021) predicted. Conditional on Spec being present in the Project; degrades cleanly when absent. Wants its own ADR before implementation since the scope is bigger than a footnote on ADR-0022.

## More Index Report categories (after v0 categories prove out)

- **Schedule rows with missing required fields** (the v0-excluded category 4) — only after extraction quality is high enough that this isn't false-positive theater.
- **Cross-document reference breakage** — e.g. schedule cites hardware set "HW-7" but no such set exists in the hardware schedule.
- **Sheet revisions out of step** — A2.01 rev 3 references A2.05 rev 2; if A2.05 rev 4 exists, flag.
- **Discipline coordination flags** — door labeled fire-rated in Architectural schedule but no corresponding life-safety mark on Life Safety drawings.
- **Sheet completeness** — sheet listed in Drawing Index but missing from set; or vice versa (this overlaps with `legacy/drawing-index-qc` — eventually consolidate).

## More query patterns (the rest of D and E)

- **Per-room/location queries** (query (c)) — needs room Entity extraction first.
- **Cross-filter coordination queries** (query (e)) — "doors with rating but no hardware set", "fixtures on the lighting plan with no circuit number."
- **Spec cross-reference queries** — "what spec section covers acoustic ceiling panels in this Project?"
- **Where-does-X-appear queries generalized** — works for any Entity type (fixtures, rooms, equipment), not just doors.
- **Browsable dashboard surface (E)** — once the SQLite schema stabilizes, a small web UI for filtering Schedules. May or may not be worth building given Claude conversation is already a usable dashboard.

## Triage queue (F)

- **Standalone triage UI** — beyond the Index Report's inline findings, a triage queue surface where the Reviewer marks each candidate Finding as investigate / false positive / real flag. Feeds back into a quality dataset for tuning.
- **Confidence scoring on Findings** — sort the queue by likelihood, top-of-queue first.

## Bluebeam Max integration (A and C)

- **`qc-core` MCP server** as the second front-end (ADR-0004) — exposes the same library functions as MCP tools so Claude Desktop can orchestrate alongside Bluebeam's MCP.
- **Click-through cross-reference (A)** — Reviewer selects a door tag in Revu → Claude Desktop calls Bluebeam MCP to read the selection, then calls `qc-core` MCP to look up all appearances of that Entity → presents the list with one-click jump-to.
- **Live anomaly highlighting (C)** — Reviewer scrolls a Sheet → Claude proactively flags structured-data discrepancies for visible Entities on the active page.
- **Round-trip markup state** — when Reviewer accepts/rejects/edits a Finding in Bluebeam, round-trip the decision back into the Assistant's database as training/feedback data.
- **Studio Project discovery** — the firm runs Reviews out of Revu Desktop with files referenced by `studio://...` URLs (e.g. `studio://studio.bluebeam.com/868-535-974/RediCheck Review/Electrical - Bldg A.pdf`). `open_file` accepts these URLs natively (empirically confirmed), so direct discipline-by-discipline orchestration over a Studio-hosted Drawing Set works today via `list_studio_projects` + the firm's `studio://<endpoint>/<ProjectID>/RediCheck Review/<DisciplinePDF>.pdf` convention documented in `docs/firm-conventions.md`. **`studio_project_search` is currently unusable** — it returns "still being indexed" on every project tested regardless of age, almost certainly a tenant-level / paid-feature gate rather than latency. Worth re-checking when Bluebeam's AI/search rollout matures, but until then the discovery path is "list projects + construct URL by convention," not "search."

## OCR fallback for raster Sheets (per ADR-0008)

- When a Project includes scanned or rasterized Sheets, fall back to OCR. Constraint: pipeline must be high-precision (distinguishes OCR'd rows from vector-extracted rows in the Index Report) and fast enough that it doesn't dominate `qc-index` runtime. Bluebeam Revu has a built-in OCR tool that may be the right call-out for some workflows; investigate options like PaddleOCR, Surya OCR, or Qianfan-OCR for headless use. Per the landscape scan ([reference](reference/competitors/aec-qc-ai-analysis.md)), **Surya OCR** is the strongest open option as of 2026 — handles rotated text natively, which matters for dimension labels. PaddleOCR-VL is the heavier alternative if we ever need visual document understanding bundled with OCR.

## Visual entity extraction (when text-first stops being enough, per ADR-0008)

ADR-0008 commits to text-first, no CV for entities — these are the relaxations to consider when a check requires extracting entities that aren't reliably present in the text layer (e.g. fixtures, sprinkler heads, electrical outlets on plans). Sourced from the [landscape analysis](reference/competitors/aec-qc-ai-analysis.md).

- **Document layout via DocLayout-YOLO** — purpose-trained on YOLOv10 backbone for titleblock / schedule / drawing-area region detection. Lower-effort entry point than symbol detection — useful even within ADR-0008's text-first stance because it crops better text-extraction regions.
- **Symbol detection via fine-tuned YOLOv11** (or RT-DETR-v2 for dense small objects) — the standard build for known symbol corpora. AGPL license; needs labeled data. The competitor doc estimates 200–500 labeled drawings beats any public dataset for a specific checklist scope.
- **Zero-shot symbol detection via Grounding DINO 1.6 + SAM 2.1** — useful before labeled data exists. Prompt with text descriptions ("circular electrical outlet with internal hatch"); manually verify high-confidence detections; use as bootstrapping labels. Standard active-learning loop.
- **Synthetic + weak labeling** as the data-bootstrap path — SESYD-style procedural floorplan rendering + Grounding-DINO weak labels, before investing in human labeling. Public datasets (CubiCasa5K is CC-BY-NC research-only; FloorPlanCAD, SESYD, ArchCAD-400K) are useful for benchmarking, not commercial training.
- **VLM over cropped regions** — Qwen2.5-VL-7B on a detail-region crop is the competitor-recommended pattern for "interpret this drawn detail" tasks (corresponds to AEC-Bench's `detail-title-accuracy` family — the hardest task per the paper). API call to Claude/GPT for highest quality; Qwen self-host for cost.

The competitor consensus per the landscape doc: off-the-shelf VLMs alone are insufficient for AEC drawings (TwinKnowledge stated this publicly). Purpose-trained CV is still the moat for high-precision visual tasks.

## Cross-sheet visual retrieval

Current direction (per ADR-0014/0015) builds the drawing index via bookmarks + titleblock cross-check — text-based. For when text retrieval breaks down (visually distinctive details, callouts without clean text targets), the landscape recommends **ColQwen2** (ViDoRe benchmark leader) — VLM patch embeddings with ColBERT-style late-interaction multi-vector retrieval. Stored in Qdrant or pgvector. Use case: "the detail sheet that matches callout 3/A-501" in a 400-page drawing set. Worth revisiting if we hit accuracy walls on `cross-reference-resolution` or `drawing-navigation` in [AEC-Bench](reference/benchmarks/aec-bench-capability-map.md) once we have baselines.

## Markup output enhancements (beyond ADR-0012)

ADR-0012 emits PyMuPDF inline annotations as the primary path. The landscape analysis surfaces two refinements worth considering once the basic emit is solid:

- **XFDF as the interchange format** — Bluebeam Markups List → Import accepts XFDF, and XFDF is a standard XML format we can produce alongside the inline annotations. Gives Reviewers a "pull just the new findings into my existing Revu session" workflow. Populate `/T` (author = "RediCheck AI" per ADR-0009 author-based convention), `/Subj`, `/Contents`, `/M`, `/NM`, `/C`.
- **Subject types that round-trip cleanly** — Square, Polygon, FreeText (no callout arrows), Ink, Line all render correctly in Bluebeam. Cloud+, Measurement/Calibrate, Count tool symbols, and custom stamps do NOT round-trip (PyMuPDF writes the geometry but Bluebeam doesn't recognize the subject). PyMuPDF FreeText also limits fonts to 5 (Helvetica, Times, Courier, ZapfDingbats, Symbol) with no bold/italic. **Implication: design Finding markups using only the round-trip-safe subjects.** If higher-fidelity Cloud+ or measurement markups become a requirement, evaluate Apryse/PDFTron or Nutrient (formerly PSPDFKit) — expensive, but the only way past PyMuPDF's subject ceiling.

## Reliability and review-loop patterns from the landscape

Sourced from [aec-qc-ai-analysis.md §C](reference/competitors/aec-qc-ai-analysis.md). Several are already implicit in current ADRs; capturing here so they're explicit when the relevant work lands.

- **Confidence-gated pipeline + quality gate** (Helonic's pattern) — every Finding gets a model-internal confidence score; the gate filters before surfacing to the Reviewer. Tension with Structured's "deterministic list" framing (and ADR-0009's author-based candidates) — we surface to the Reviewer as a deterministic list, but internally a confidence score on each Finding could power suppression and the Triage queue (F). Worth an ADR before adopting.
- **Issue grouping + severity** — Buildcheck explicitly clusters repeated instances of the same issue type so they can be dismissed in bulk. Aligns with future Triage queue work (F). The Index Report already groups by category — extend the model to entity-level clustering for door-check and other entity-based Findings.
- **Two-stage verification** — cheap LLM proposes a Finding → expensive LLM verifies before emit. Cuts false positives at the cost of double-call latency. Worth keeping in pocket if false-positive rate ever exceeds the Reviewer's patience threshold.
- **Per-Project / per-customer adaptation** (Firmus' pattern) — learn to suppress redundant comments by Project context (e.g. residential unit plans repeat the same layout 40×; suppress repeat Findings). Relates to the Cross-Project knowledge layer below.
- **Source citations on every Finding** — table-stakes per the landscape. Already covered: ADR-0012's markup-on-sheet plus a record in `qc.sqlite` IS the citation. No new work needed; calling it out so we don't drop it.

## Eval / regression infrastructure (beyond AEC-Bench)

[AEC-Bench](reference/benchmarks/aec-bench-capability-map.md) is the external benchmark. Internal regression infrastructure that complements it:

- **Inspect AI (UK AISI)** as the eval runner — works alongside Harbor for the AEC-Bench external runs and can drive our own internal labeled-archive suite. Lower-overhead than rolling pytest-based eval ourselves once we have more than a handful of fixture sets.
- **Labeled archive from the family business / pilot Projects** — the landscape doc calls this "the moat" (what Document Crunch internally calls ConstructBench). 30–50 hand-labeled Projects against the current skill outputs gives us a private regression suite that's higher-signal than AEC-Bench for our specific checklist coverage. Cross-references with the "Snapshot regression testing" item below.

## Cross-Project / firm-wide adaptation (deferred, per ADR-0004)

Already noted as the Cross-Project knowledge layer. Landscape doc reinforces this is where competitors (Firmus, Buildcheck via patents) build retention moats — firm-specific suppression rules, repeated-pattern recognition across multiple Projects in an archive. Distinct scope; revisit after single-Project skills generalize.

## Markup-writing (deferred deliberately, per ADR-0002)

- The Assistant explicitly does **not** write Markups in v0. If we ever revisit, candidates: importing the legacy `.bax` round-trip; writing markups via Bluebeam MCP in a "draft markups for Reviewer to review and ship" mode (never autonomous).

## Cross-Project knowledge layer (deferred, per ADR-0004)

- Firm-wide archive of past Reviews as a separate data layer. Patterns that recur across Projects, common spec language, Reviewer-specific preferences. Real value but a different scope — needs its own design pass.

## Tool-set distribution

- Ship updated `.btx` tool sets (RC-Electrical, RC-Mechanical, RC-Landscape and others) as part of the package so Reviewers' Bluebeam workflow stays consistent across the firm.

## Other ideas surfaced

- **Working-folder convention via Cowork** — for v0 the skill takes a path; eventually use Cowork's workspace root and add a manifest file at `<project>/.qc/project.yaml` to remember Column Mappers and Project-specific configuration.
- **Snapshot regression testing** — golden Index Reports per Project; any extraction change must explain diffs against the snapshots.
- **Anonymized fixtures** — when public shipping (ADR-0001) requires demo/example data, anonymization becomes its own separate project focused solely on PII scrubbing of client names, locations, embedded photos, and identifying details. Not bundled with `qc-core` development.
