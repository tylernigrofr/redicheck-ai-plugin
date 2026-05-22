# Firm conventions

Observed conventions in how RediCheck structures its work in Bluebeam Studio and on disk. These are *facts about the firm's workflow*, not architectural decisions — code may assume them as defaults but must degrade gracefully when a Project doesn't follow them. Update this file when a convention changes or a new one becomes visible.

## Studio Project layout

Drawing Sets live in Bluebeam Studio Projects. Each Project's review-ready PDFs sit under a top-level folder named exactly `RediCheck Review/`, with one PDF per discipline (or per discipline-plus-building when a Project has multiple buildings). Observed file shapes from Project `868-535-974` (Abbot Kinney):

```
studio://<endpoint>/868-535-974/RediCheck Review/Architectural and Structural.pdf
studio://<endpoint>/868-535-974/RediCheck Review/Electrical - Bldg A.pdf
studio://<endpoint>/868-535-974/RediCheck Review/Electrical - Bldg B.pdf
studio://<endpoint>/868-535-974/RediCheck Review/FoodService.pdf
studio://<endpoint>/868-535-974/RediCheck Review/Mechanical - Bldg A.pdf
studio://<endpoint>/868-535-974/RediCheck Review/Mechanical - Bldg B.pdf
studio://<endpoint>/868-535-974/RediCheck Review/Plumbing - Bldg A.pdf
studio://<endpoint>/868-535-974/RediCheck Review/Plumbing - Bldg B.pdf
```

Three patterns to handle:

1. **Combined disciplines** (e.g. `Architectural and Structural.pdf`) — a single PDF carries multiple disciplines, separable only by sheet-number prefix or rotation per page. Discipline routing must therefore happen at the sheet level via `get_page_information`, not the file level.
2. **Per-building splits** (e.g. `Electrical - Bldg A.pdf` / `Electrical - Bldg B.pdf`) — same discipline, different buildings. The discovery layer must enumerate all matching files rather than assume one PDF per discipline.
3. **Discipline naming variance** — `FoodService` (no separator) vs `Mechanical - Bldg A` (space-dash-space). Filename matching needs to be loose.

The Spec is **not** in `RediCheck Review/`; it lives elsewhere in the Project tree under its own conventional name (`Specs.pdf`, `Project Manual.pdf`, multi-volume variants — see issue #6, #7). Treat Spec discovery as a separate problem from Drawing Set discovery.

## Studio identifiers

Each Studio Project has three IDs returned by `list_studio_projects`:

- **`PublicID`** — dashed format like `868-535-974`. The user-facing identifier; appears in `studio://` URLs.
- **`Guid`** — durable internal identifier. Use this as the primary key if/when we store anything per-Project in `qc.sqlite` or elsewhere.
- **`UniqueId`** — third flavor, role unclear; ignore unless we find a use for it.

## Studio endpoint quirk

`list_studio_projects` returns `EndPoint = "internalapi.bluebeam.com"` on every project, **not** the `studio.bluebeam.com` host that appears in the `studio://` URLs and in the Bluebeam MCP tool descriptions. Constructing `studio://` URLs from the returned `EndPoint` field will produce URLs that don't work. The right approach: use the literal `studio.bluebeam.com` host (or whatever appears in a known-good URL from Revu) rather than substituting the API endpoint.
