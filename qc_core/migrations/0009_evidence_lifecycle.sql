-- Migration 0009: Evidence lifecycle + reconciliation matrix (ADR-0026)
--
-- findings.status carries the Evidence -> Candidate -> Finding progression:
--   evidence  : tool output pending Claude judgment (no verdict yet)
--   candidate : promoted (by deterministic baseline on clean scopes, or by a
--               judgment node) and pending Reviewer triage
--   accepted  : Reviewer-accepted Finding (ADR-0024 Resolution)
--   dismissed : terminal off-ramp (Claude or Reviewer rejected it)
-- Existing rows default to 'candidate' (they were tool-concluded and pending
-- the Reviewer when this migration landed).

ALTER TABLE findings ADD COLUMN status TEXT NOT NULL DEFAULT 'candidate'
    CHECK (status IN ('evidence', 'candidate', 'accepted', 'dismissed'));
ALTER TABLE findings ADD COLUMN judgment_rationale TEXT;
ALTER TABLE findings ADD COLUMN evidence_key TEXT;

CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status);

-- One row per (check, entity-key, channel, volume): what each channel says
-- about each entity, with provenance. The Evidence artifact a reconciliation
-- tool emits without a verdict (CONTEXT.md: Reconciliation Matrix).
CREATE TABLE IF NOT EXISTS reconciliation_matrix (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    check_name TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    channel TEXT NOT NULL,
    volume_id INTEGER,
    present INTEGER NOT NULL DEFAULT 1,
    raw_value TEXT,
    page INTEGER,
    detail TEXT,
    UNIQUE (check_name, entity_key, channel, volume_id)
);

CREATE INDEX IF NOT EXISTS idx_matrix_check_key
    ON reconciliation_matrix(check_name, entity_key);

-- Fail-loud invariant evaluations over the matrix (ADR-0026 section 6).
-- A row with status='tripped' marks its scope untrusted: emit exits non-zero
-- until the row is 'resolved' (judgment node investigated, rationale recorded)
-- or 'overridden' (Reviewer resolution, ADR-0024).
CREATE TABLE IF NOT EXISTS invariant_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    check_name TEXT NOT NULL,
    invariant TEXT NOT NULL,
    scope TEXT,
    status TEXT NOT NULL DEFAULT 'tripped'
        CHECK (status IN ('tripped', 'resolved', 'overridden')),
    detail TEXT,
    rationale TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (check_name, invariant, scope)
);
