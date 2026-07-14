CREATE TABLE IF NOT EXISTS paper_cash_flow (
    cash_flow_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    applied_at TEXT,
    flow_type TEXT NOT NULL CHECK(flow_type IN ('deposit', 'withdrawal')),
    amount REAL NOT NULL CHECK(amount > 0),
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'applied', 'rejected', 'cancelled')),
    source TEXT NOT NULL DEFAULT 'app' CHECK(source IN ('app', 'cli', 'scheduled', 'backfill')),
    run_id TEXT,
    idempotency_key TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_cash_flow_idempotency
ON paper_cash_flow(user_id, idempotency_key)
WHERE idempotency_key IS NOT NULL AND idempotency_key <> '';

CREATE INDEX IF NOT EXISTS idx_paper_cash_flow_user_date
ON paper_cash_flow(user_id, effective_date);

ALTER TABLE paper_account ADD COLUMN cumulative_deposit REAL DEFAULT 0;
ALTER TABLE paper_account ADD COLUMN cumulative_withdrawal REAL DEFAULT 0;
ALTER TABLE paper_account ADD COLUMN net_contribution REAL DEFAULT 0;
ALTER TABLE paper_account ADD COLUMN absolute_profit REAL DEFAULT 0;
ALTER TABLE paper_account ADD COLUMN time_weighted_return REAL DEFAULT 0;
