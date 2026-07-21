ALTER TABLE paper_order ADD COLUMN strategy_id TEXT NOT NULL DEFAULT '';
ALTER TABLE paper_order ADD COLUMN strategy_version TEXT NOT NULL DEFAULT '';
ALTER TABLE paper_order ADD COLUMN binding_id TEXT NOT NULL DEFAULT '';
ALTER TABLE paper_order ADD COLUMN config_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE paper_order ADD COLUMN resolved_config_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE paper_trading_settings ADD COLUMN target_invested_weight REAL NOT NULL DEFAULT 0.80;

ALTER TABLE paper_account_snapshot ADD COLUMN strategy_id TEXT NOT NULL DEFAULT '';
ALTER TABLE paper_account_snapshot ADD COLUMN strategy_version TEXT NOT NULL DEFAULT '';
ALTER TABLE paper_account_snapshot ADD COLUMN binding_id TEXT NOT NULL DEFAULT '';
ALTER TABLE paper_account_snapshot ADD COLUMN config_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE paper_account_snapshot ADD COLUMN resolved_config_json TEXT NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS paper_strategy_execution_history (
    execution_history_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    run_id TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    binding_id TEXT NOT NULL DEFAULT '',
    config_hash TEXT NOT NULL,
    resolved_config_json TEXT NOT NULL DEFAULT '{}',
    positions_before_json TEXT NOT NULL DEFAULT '[]',
    target_portfolio_json TEXT NOT NULL DEFAULT '[]',
    orders_json TEXT NOT NULL DEFAULT '[]',
    positions_after_json TEXT NOT NULL DEFAULT '[]',
    cash_before REAL NOT NULL DEFAULT 0,
    cash_after REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_strategy_execution_history_scope
ON paper_strategy_execution_history(user_id, account_id, trade_date, created_at);

CREATE INDEX IF NOT EXISTS idx_strategy_execution_history_binding
ON paper_strategy_execution_history(binding_id, trade_date);
