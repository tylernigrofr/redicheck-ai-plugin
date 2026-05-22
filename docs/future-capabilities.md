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

- When a Project includes scanned or rasterized Sheets, fall back to OCR. Constraint: pipeline must be high-precision (distinguishes OCR'd rows from vector-extracted rows in the Index Report) and fast enough that it doesn't dominate `qc-index` runtime. Bluebeam Revu has a built-in OCR tool that may be the right call-out for some workflows; investigate options like PaddleOCR, Surya OCR, or Qianfan-OCR for headless use.

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
