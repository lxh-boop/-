CREATE TABLE IF NOT EXISTS paper_nav_history (
    nav_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    cash REAL NOT NULL DEFAULT 0,
    position_market_value REAL NOT NULL DEFAULT 0,
    total_assets REAL NOT NULL DEFAULT 0,
    net_contribution REAL NOT NULL DEFAULT 0,
    daily_deposit REAL NOT NULL DEFAULT 0,
    daily_withdrawal REAL NOT NULL DEFAULT 0,
    daily_fee REAL NOT NULL DEFAULT 0,
    cumulative_fee REAL NOT NULL DEFAULT 0,
    daily_profit REAL NOT NULL DEFAULT 0,
    daily_return REAL NOT NULL DEFAULT 0,
    cumulative_return REAL NOT NULL DEFAULT 0,
    time_weighted_return REAL NOT NULL DEFAULT 0,
    nav REAL NOT NULL DEFAULT 1,
    nav_peak REAL NOT NULL DEFAULT 1,
    drawdown REAL NOT NULL DEFAULT 0,
    position_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_paper_nav_history_user_date
    ON paper_nav_history(user_id, trade_date);

CREATE TABLE IF NOT EXISTS paper_trading_settings (
    settings_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    entry_top_k INTEGER NOT NULL DEFAULT 10,
    hold_buffer_rank INTEGER NOT NULL DEFAULT 15,
    max_positions INTEGER NOT NULL DEFAULT 10,
    minimum_cash_ratio REAL NOT NULL DEFAULT 0.05,
    min_rebalance_weight_delta REAL NOT NULL DEFAULT 0.01,
    strategy_mode TEXT NOT NULL DEFAULT 'top10_score_weighted',
    buy_cost_rate REAL NOT NULL DEFAULT 0.0003,
    sell_cost_rate REAL NOT NULL DEFAULT 0.0008,
    minimum_fee REAL NOT NULL DEFAULT 0,
    slippage_rate REAL NOT NULL DEFAULT 0,
    execution_price_type TEXT NOT NULL DEFAULT 'close',
    effective_date TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_paper_trading_settings_user
    ON paper_trading_settings(user_id, effective_date);

CREATE TABLE IF NOT EXISTS paper_account_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    cash REAL NOT NULL DEFAULT 0,
    position_market_value REAL NOT NULL DEFAULT 0,
    total_assets REAL NOT NULL DEFAULT 0,
    net_contribution REAL NOT NULL DEFAULT 0,
    daily_return REAL NOT NULL DEFAULT 0,
    cumulative_return REAL NOT NULL DEFAULT 0,
    time_weighted_return REAL NOT NULL DEFAULT 0,
    nav REAL NOT NULL DEFAULT 1,
    drawdown REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_paper_account_snapshot_user_date
    ON paper_account_snapshot(user_id, trade_date);

ALTER TABLE paper_order ADD COLUMN gross_amount REAL NOT NULL DEFAULT 0;
ALTER TABLE paper_order ADD COLUMN commission_fee REAL NOT NULL DEFAULT 0;
ALTER TABLE paper_order ADD COLUMN other_fee REAL NOT NULL DEFAULT 0;
ALTER TABLE paper_order ADD COLUMN slippage_cost REAL NOT NULL DEFAULT 0;
ALTER TABLE paper_order ADD COLUMN total_fee REAL NOT NULL DEFAULT 0;
ALTER TABLE paper_order ADD COLUMN net_cash_change REAL NOT NULL DEFAULT 0;
ALTER TABLE paper_order ADD COLUMN applied_buy_cost_rate REAL NOT NULL DEFAULT 0;
ALTER TABLE paper_order ADD COLUMN applied_sell_cost_rate REAL NOT NULL DEFAULT 0;

ALTER TABLE paper_decision_log ADD COLUMN total_fee REAL NOT NULL DEFAULT 0;
ALTER TABLE paper_decision_log ADD COLUMN net_cash_change REAL NOT NULL DEFAULT 0;

ALTER TABLE paper_account ADD COLUMN daily_fee REAL NOT NULL DEFAULT 0;
ALTER TABLE paper_account ADD COLUMN cumulative_fee REAL NOT NULL DEFAULT 0;
ALTER TABLE paper_account ADD COLUMN position_market_value REAL NOT NULL DEFAULT 0;
ALTER TABLE paper_account ADD COLUMN nav REAL NOT NULL DEFAULT 1;
ALTER TABLE paper_account ADD COLUMN drawdown REAL NOT NULL DEFAULT 0;
