PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS portfolios (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_loans (
    id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL REFERENCES portfolios(id),
    external_loan_id TEXT NOT NULL,
    loan_order INTEGER NOT NULL CHECK (loan_order >= 0),
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (portfolio_id, external_loan_id),
    UNIQUE (portfolio_id, loan_order)
);

CREATE TABLE IF NOT EXISTS priority_assessment_batches (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id TEXT NOT NULL REFERENCES portfolios(id),
    batch_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (portfolio_id, batch_id),
    UNIQUE (sequence, portfolio_id, batch_id)
);

CREATE TABLE IF NOT EXISTS priority_assessments (
    id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL,
    batch_sequence INTEGER NOT NULL,
    batch_id TEXT NOT NULL,
    external_loan_id TEXT NOT NULL,
    rank_order INTEGER NOT NULL CHECK (rank_order >= 0),
    formula_version TEXT NOT NULL,
    ruleset_version TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (portfolio_id, external_loan_id)
        REFERENCES portfolio_loans(portfolio_id, external_loan_id),
    FOREIGN KEY (batch_sequence, portfolio_id, batch_id)
        REFERENCES priority_assessment_batches(sequence, portfolio_id, batch_id),
    UNIQUE (portfolio_id, batch_id, external_loan_id),
    UNIQUE (portfolio_id, batch_id, rank_order)
);

CREATE TABLE IF NOT EXISTS portfolio_investigations (
    id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL UNIQUE REFERENCES portfolios(id),
    external_loan_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (portfolio_id, external_loan_id)
        REFERENCES portfolio_loans(portfolio_id, external_loan_id)
);

CREATE TABLE IF NOT EXISTS contradictions (
    id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL,
    external_loan_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (portfolio_id, external_loan_id)
        REFERENCES portfolio_loans(portfolio_id, external_loan_id)
);

CREATE TABLE IF NOT EXISTS vendor_selections (
    id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL,
    external_loan_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (portfolio_id, external_loan_id)
        REFERENCES portfolio_loans(portfolio_id, external_loan_id)
);

CREATE TABLE IF NOT EXISTS exposure_estimates (
    id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL,
    external_loan_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('before_rescue', 'after_rescue')),
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (portfolio_id, external_loan_id)
        REFERENCES portfolio_loans(portfolio_id, external_loan_id),
    UNIQUE (portfolio_id, external_loan_id, stage)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_loans_portfolio
    ON portfolio_loans(portfolio_id, external_loan_id);
CREATE INDEX IF NOT EXISTS idx_priority_portfolio_rank
    ON priority_assessments(portfolio_id, batch_id, rank_order);
CREATE INDEX IF NOT EXISTS idx_priority_portfolio_batch_created
    ON priority_assessment_batches(portfolio_id, sequence DESC);
CREATE INDEX IF NOT EXISTS idx_priority_loan
    ON priority_assessments(portfolio_id, external_loan_id);
CREATE INDEX IF NOT EXISTS idx_investigations_loan
    ON portfolio_investigations(portfolio_id, external_loan_id);
CREATE INDEX IF NOT EXISTS idx_contradictions_loan_created
    ON contradictions(portfolio_id, external_loan_id, created_at);
CREATE INDEX IF NOT EXISTS idx_vendor_selections_loan_created
    ON vendor_selections(portfolio_id, external_loan_id, created_at);
CREATE INDEX IF NOT EXISTS idx_exposure_estimates_loan_stage
    ON exposure_estimates(portfolio_id, external_loan_id, stage);

CREATE TRIGGER IF NOT EXISTS priority_assessments_immutable_update
BEFORE UPDATE ON priority_assessments BEGIN
    SELECT RAISE(ABORT, 'priority assessment snapshots are immutable');
END;

CREATE TRIGGER IF NOT EXISTS priority_assessment_batches_immutable_update
BEFORE UPDATE ON priority_assessment_batches BEGIN
    SELECT RAISE(ABORT, 'priority assessment batch snapshots are immutable');
END;
CREATE TRIGGER IF NOT EXISTS priority_assessment_batches_immutable_delete
BEFORE DELETE ON priority_assessment_batches BEGIN
    SELECT RAISE(ABORT, 'priority assessment batch snapshots are immutable');
END;
CREATE TRIGGER IF NOT EXISTS priority_assessments_immutable_delete
BEFORE DELETE ON priority_assessments BEGIN
    SELECT RAISE(ABORT, 'priority assessment snapshots are immutable');
END;

CREATE TRIGGER IF NOT EXISTS portfolio_investigations_immutable_update
BEFORE UPDATE ON portfolio_investigations BEGIN
    SELECT RAISE(ABORT, 'portfolio investigation snapshots are immutable');
END;
CREATE TRIGGER IF NOT EXISTS portfolio_investigations_immutable_delete
BEFORE DELETE ON portfolio_investigations BEGIN
    SELECT RAISE(ABORT, 'portfolio investigation snapshots are immutable');
END;

CREATE TRIGGER IF NOT EXISTS contradictions_immutable_update
BEFORE UPDATE ON contradictions BEGIN
    SELECT RAISE(ABORT, 'contradiction snapshots are immutable');
END;
CREATE TRIGGER IF NOT EXISTS contradictions_immutable_delete
BEFORE DELETE ON contradictions BEGIN
    SELECT RAISE(ABORT, 'contradiction snapshots are immutable');
END;

CREATE TRIGGER IF NOT EXISTS vendor_selections_immutable_update
BEFORE UPDATE ON vendor_selections BEGIN
    SELECT RAISE(ABORT, 'vendor selection snapshots are immutable');
END;
CREATE TRIGGER IF NOT EXISTS vendor_selections_immutable_delete
BEFORE DELETE ON vendor_selections BEGIN
    SELECT RAISE(ABORT, 'vendor selection snapshots are immutable');
END;

CREATE TRIGGER IF NOT EXISTS exposure_estimates_immutable_update
BEFORE UPDATE ON exposure_estimates BEGIN
    SELECT RAISE(ABORT, 'exposure estimate snapshots are immutable');
END;
CREATE TRIGGER IF NOT EXISTS exposure_estimates_immutable_delete
BEFORE DELETE ON exposure_estimates BEGIN
    SELECT RAISE(ABORT, 'exposure estimate snapshots are immutable');
END;
