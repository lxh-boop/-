CREATE TABLE IF NOT EXISTS strategy_bindings (
    binding_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    status TEXT NOT NULL,
    previous_binding_id TEXT,
    source_plan_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    activated_at TEXT,
    disabled_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_strategy_bindings_active_account
ON strategy_bindings(user_id, account_id)
WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_strategy_bindings_scope_history
ON strategy_bindings(user_id, account_id, effective_from, created_at);
