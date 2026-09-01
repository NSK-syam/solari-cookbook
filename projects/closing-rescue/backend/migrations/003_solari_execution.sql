CREATE TABLE solari_executions (
    portfolio_id TEXT PRIMARY KEY REFERENCES portfolios(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
