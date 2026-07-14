DROP TABLE IF EXISTS agent_decision_log_stage35;
CREATE TABLE agent_decision_log_stage35 (
    decision_id TEXT PRIMARY KEY,
    user_id TEXT,
    trade_date TEXT,
    stock_code TEXT,
    original_pred_score REAL,
    original_pred_rank INTEGER,
    news_adjustment TEXT,
    risk_adjustment TEXT,
    user_constraint TEXT,
    triggered_rules TEXT,
    combined_adjustment REAL,
    position_adjustment_ratio REAL,
    final_reason TEXT,
    evidence_news_ids TEXT,
    evidence_chunk_ids TEXT,
    evidence_snapshot TEXT,
    retrieval_id TEXT,
    future_return_1d REAL,
    future_return_5d REAL,
    is_effective INTEGER,
    job_id TEXT,
    run_id TEXT,
    execution_source TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

INSERT OR REPLACE INTO agent_decision_log_stage35 (
    decision_id, user_id, trade_date, stock_code, original_pred_score, original_pred_rank,
    news_adjustment, risk_adjustment, user_constraint, triggered_rules,
    combined_adjustment, position_adjustment_ratio, final_reason,
    evidence_news_ids, evidence_chunk_ids, evidence_snapshot, retrieval_id,
    future_return_1d, future_return_5d, is_effective,
    job_id, run_id, execution_source, created_at
)
SELECT
    decision_id, user_id, trade_date, stock_code, original_pred_score, original_pred_rank,
    news_adjustment, risk_adjustment, user_constraint, triggered_rules,
    0.0 AS combined_adjustment, 1.0 AS position_adjustment_ratio, final_reason,
    evidence_news_ids, evidence_chunk_ids, evidence_snapshot, retrieval_id,
    future_return_1d, future_return_5d, is_effective,
    job_id, run_id, execution_source, created_at
FROM agent_decision_log;

DROP TABLE agent_decision_log;
ALTER TABLE agent_decision_log_stage35 RENAME TO agent_decision_log;

DROP TABLE IF EXISTS paper_order_stage35;
CREATE TABLE paper_order_stage35 (
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
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    decision_id TEXT,
    decision_time TEXT,
    paper_action TEXT,
    current_weight REAL,
    order_amount REAL,
    risk_warning TEXT,
    triggered_rules TEXT,
    job_id TEXT,
    run_id TEXT,
    execution_source TEXT,
    gross_amount REAL NOT NULL DEFAULT 0,
    commission_fee REAL NOT NULL DEFAULT 0,
    other_fee REAL NOT NULL DEFAULT 0,
    slippage_cost REAL NOT NULL DEFAULT 0,
    total_fee REAL NOT NULL DEFAULT 0,
    net_cash_change REAL NOT NULL DEFAULT 0,
    applied_buy_cost_rate REAL NOT NULL DEFAULT 0,
    applied_sell_cost_rate REAL NOT NULL DEFAULT 0
);

INSERT OR REPLACE INTO paper_order_stage35 (
    order_id, user_id, account_id, trade_date, stock_code, stock_name,
    action, target_weight, executed_price, quantity, reason, is_paper_trading, created_at,
    decision_id, decision_time, paper_action, current_weight, order_amount,
    risk_warning, triggered_rules, job_id, run_id, execution_source,
    gross_amount, commission_fee, other_fee, slippage_cost, total_fee,
    net_cash_change, applied_buy_cost_rate, applied_sell_cost_rate
)
SELECT
    order_id, user_id, account_id, trade_date, stock_code, stock_name,
    action, target_weight, executed_price, quantity, reason, is_paper_trading, created_at,
    decision_id, decision_time, paper_action, current_weight, order_amount,
    risk_warning, triggered_rules, job_id, run_id, execution_source,
    gross_amount, commission_fee, other_fee, slippage_cost, total_fee,
    net_cash_change, applied_buy_cost_rate, applied_sell_cost_rate
FROM paper_order;

DROP TABLE paper_order;
ALTER TABLE paper_order_stage35 RENAME TO paper_order;

DROP TABLE IF EXISTS paper_decision_log_stage35;
CREATE TABLE paper_decision_log_stage35 (
    decision_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    trade_date TEXT,
    decision_time TEXT,
    stock_code TEXT,
    stock_name TEXT,
    paper_action TEXT,
    target_weight REAL,
    current_weight REAL,
    order_amount REAL,
    order_quantity REAL,
    executed_price REAL,
    total_fee REAL NOT NULL DEFAULT 0,
    net_cash_change REAL NOT NULL DEFAULT 0,
    original_rank INTEGER,
    original_score REAL,
    news_adjustment REAL,
    user_adjustment REAL,
    effective_news_adjustment REAL,
    combined_adjustment REAL,
    position_adjustment_ratio REAL,
    reason TEXT,
    risk_warning TEXT,
    triggered_rules TEXT,
    source_decision_id TEXT,
    job_id TEXT,
    run_id TEXT,
    execution_source TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

INSERT OR REPLACE INTO paper_decision_log_stage35 (
    decision_id, user_id, trade_date, decision_time, stock_code, stock_name,
    paper_action, target_weight, current_weight, order_amount, order_quantity,
    executed_price, total_fee, net_cash_change,
    original_rank, original_score, news_adjustment, user_adjustment,
    effective_news_adjustment, combined_adjustment, position_adjustment_ratio,
    reason, risk_warning, triggered_rules, source_decision_id,
    job_id, run_id, execution_source, created_at
)
SELECT
    decision_id, user_id, trade_date, decision_time, stock_code, stock_name,
    paper_action, target_weight, current_weight, order_amount, order_quantity,
    executed_price, 0.0 AS total_fee, 0.0 AS net_cash_change,
    0 AS original_rank, 0.0 AS original_score, 0.0 AS news_adjustment, 0.0 AS user_adjustment,
    0.0 AS effective_news_adjustment, 0.0 AS combined_adjustment, 1.0 AS position_adjustment_ratio,
    reason, risk_warning, triggered_rules, source_decision_id,
    job_id, run_id, execution_source, created_at
FROM paper_decision_log;

DROP TABLE paper_decision_log;
ALTER TABLE paper_decision_log_stage35 RENAME TO paper_decision_log;

CREATE INDEX IF NOT EXISTS idx_agent_decision_log_date ON agent_decision_log(trade_date);
CREATE INDEX IF NOT EXISTS idx_agent_decision_log_stock ON agent_decision_log(stock_code);
CREATE INDEX IF NOT EXISTS idx_agent_decision_log_user ON agent_decision_log(user_id);
CREATE INDEX IF NOT EXISTS idx_paper_order_user ON paper_order(user_id);
CREATE INDEX IF NOT EXISTS idx_paper_order_date ON paper_order(trade_date);
CREATE INDEX IF NOT EXISTS idx_paper_order_stock ON paper_order(stock_code);
CREATE INDEX IF NOT EXISTS idx_paper_decision_log_user ON paper_decision_log(user_id);
CREATE INDEX IF NOT EXISTS idx_paper_decision_log_date ON paper_decision_log(trade_date);
