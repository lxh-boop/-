CREATE TABLE IF NOT EXISTS paper_replay_run (
    run_id TEXT PRIMARY KEY,
    user_id TEXT,
    start_date TEXT,
    end_date TEXT,
    status TEXT,
    strategy_version TEXT,
    created_at TEXT,
    completed_at TEXT,
    failed_trade_dates TEXT,
    failure_reasons TEXT,
    continued_after_failure_count INTEGER DEFAULT 0,
    manifest_path TEXT
);

CREATE TABLE IF NOT EXISTS paper_daily_replay_audit (
    daily_audit_id TEXT PRIMARY KEY,
    run_id TEXT,
    user_id TEXT,
    trade_date TEXT,
    status TEXT,
    original_ranking_count INTEGER DEFAULT 0,
    ai_adjustment_count INTEGER DEFAULT 0,
    candidate_count INTEGER DEFAULT 0,
    target_position_count INTEGER DEFAULT 0,
    buy_count INTEGER DEFAULT 0,
    sell_count INTEGER DEFAULT 0,
    opening_position_count INTEGER DEFAULT 0,
    closing_position_count INTEGER DEFAULT 0,
    cash REAL DEFAULT 0,
    position_market_value REAL DEFAULT 0,
    total_asset REAL DEFAULT 0,
    audit_json_path TEXT,
    audit_md_path TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_paper_daily_replay_audit_run ON paper_daily_replay_audit(run_id);
CREATE INDEX IF NOT EXISTS idx_paper_daily_replay_audit_user_date ON paper_daily_replay_audit(user_id, trade_date);

CREATE TABLE IF NOT EXISTS paper_stock_decision_audit (
    stock_decision_audit_id TEXT PRIMARY KEY,
    run_id TEXT,
    user_id TEXT,
    trade_date TEXT,
    stock_code TEXT,
    original_rank INTEGER,
    final_rank INTEGER,
    base_weight REAL,
    stored_ai_adjustment TEXT,
    target_weight REAL,
    target_quantity REAL,
    executed_quantity REAL,
    decision TEXT,
    reason_code TEXT,
    reason_detail TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_paper_stock_decision_audit_run ON paper_stock_decision_audit(run_id);
CREATE INDEX IF NOT EXISTS idx_paper_stock_decision_audit_stock ON paper_stock_decision_audit(stock_code);

CREATE TABLE IF NOT EXISTS paper_order_reason_audit (
    order_reason_audit_id TEXT PRIMARY KEY,
    run_id TEXT,
    user_id TEXT,
    trade_date TEXT,
    order_id TEXT,
    stock_code TEXT,
    paper_action TEXT,
    quantity REAL DEFAULT 0,
    reason_code TEXT,
    reason_detail TEXT,
    audit_json_path TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_paper_order_reason_audit_run ON paper_order_reason_audit(run_id);
CREATE INDEX IF NOT EXISTS idx_paper_order_reason_audit_order ON paper_order_reason_audit(order_id);
