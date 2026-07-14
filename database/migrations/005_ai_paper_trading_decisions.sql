ALTER TABLE paper_order ADD COLUMN decision_id TEXT;
ALTER TABLE paper_order ADD COLUMN decision_time TEXT;
ALTER TABLE paper_order ADD COLUMN paper_action TEXT;
ALTER TABLE paper_order ADD COLUMN final_action TEXT;
ALTER TABLE paper_order ADD COLUMN final_score REAL;
ALTER TABLE paper_order ADD COLUMN current_weight REAL;
ALTER TABLE paper_order ADD COLUMN order_amount REAL;
ALTER TABLE paper_order ADD COLUMN risk_warning TEXT;
ALTER TABLE paper_order ADD COLUMN triggered_rules TEXT;

CREATE TABLE IF NOT EXISTS paper_decision_log (
    decision_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    trade_date TEXT,
    decision_time TEXT,
    stock_code TEXT,
    stock_name TEXT,
    final_score REAL,
    final_action TEXT,
    paper_action TEXT,
    target_weight REAL,
    current_weight REAL,
    order_amount REAL,
    order_quantity REAL,
    reason TEXT,
    risk_warning TEXT,
    triggered_rules TEXT,
    source_decision_id TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_paper_decision_log_user ON paper_decision_log(user_id);
CREATE INDEX IF NOT EXISTS idx_paper_decision_log_date ON paper_decision_log(trade_date);
