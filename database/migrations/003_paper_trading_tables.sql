CREATE TABLE IF NOT EXISTS paper_account (
    account_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    initial_cash REAL,
    cash REAL,
    total_assets REAL,
    daily_return REAL,
    cumulative_return REAL,
    max_drawdown REAL,
    is_paper_trading INTEGER DEFAULT 1,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_paper_account_user ON paper_account(user_id);

CREATE TABLE IF NOT EXISTS paper_order (
    order_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    account_id TEXT,
    trade_date TEXT,
    stock_code TEXT,
    stock_name TEXT,
    action TEXT,
    target_weight REAL,
    executed_price REAL,
    quantity REAL,
    reason TEXT,
    is_paper_trading INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_paper_order_user ON paper_order(user_id);
CREATE INDEX IF NOT EXISTS idx_paper_order_date ON paper_order(trade_date);
CREATE INDEX IF NOT EXISTS idx_paper_order_stock ON paper_order(stock_code);
