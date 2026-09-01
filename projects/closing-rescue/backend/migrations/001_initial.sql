PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    external_case_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    disposition TEXT,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id),
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id),
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id),
    idempotency_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id),
    approval_id TEXT NOT NULL REFERENCES approvals(id),
    idempotency_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id),
    event_type TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_case ON evidence(case_id, created_at);
CREATE INDEX IF NOT EXISTS idx_decisions_case ON decisions(case_id, created_at);
CREATE INDEX IF NOT EXISTS idx_approvals_case ON approvals(case_id, created_at);
CREATE INDEX IF NOT EXISTS idx_actions_case ON actions(case_id, created_at);
CREATE INDEX IF NOT EXISTS idx_events_case ON audit_events(case_id, created_at);

CREATE TRIGGER IF NOT EXISTS decisions_immutable_update
BEFORE UPDATE ON decisions
BEGIN
    SELECT RAISE(ABORT, 'decision snapshots are immutable');
END;

CREATE TRIGGER IF NOT EXISTS decisions_immutable_delete
BEFORE DELETE ON decisions
BEGIN
    SELECT RAISE(ABORT, 'decision snapshots are immutable');
END;

CREATE TRIGGER IF NOT EXISTS audit_events_append_only_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit events are append only');
END;

CREATE TRIGGER IF NOT EXISTS audit_events_append_only_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit events are append only');
END;
