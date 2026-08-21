ALTER TABLE model_prediction ADD COLUMN prediction_for_date TEXT;
ALTER TABLE model_prediction ADD COLUMN stock_name TEXT;
ALTER TABLE model_prediction ADD COLUMN risk_level TEXT;
ALTER TABLE model_prediction ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'ranking';
ALTER TABLE model_prediction ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE model_prediction ADD COLUMN updated_at TEXT;

ALTER TABLE user_profile ADD COLUMN profile_type TEXT NOT NULL DEFAULT '稳健型';
ALTER TABLE user_profile ADD COLUMN trading_permissions_json TEXT NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_model_prediction_latest
    ON model_prediction(source_kind, trade_date, model_name, pred_rank);

CREATE TABLE IF NOT EXISTS portfolio_recommendation_result (
    recommendation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL DEFAULT '',
    original_rank INTEGER,
    combined_adjustment REAL,
    target_weight REAL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, trade_date, stock_code, model_name)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_recommendation_latest
    ON portfolio_recommendation_result(user_id, trade_date, original_rank);

CREATE TABLE IF NOT EXISTS portfolio_risk_snapshot (
    risk_snapshot_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    account_id TEXT NOT NULL DEFAULT '',
    as_of_date TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_risk_snapshot_latest
    ON portfolio_risk_snapshot(user_id, as_of_date);

CREATE TABLE IF NOT EXISTS runtime_data_import_audit (
    import_id TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_row_count INTEGER NOT NULL DEFAULT 0,
    imported_row_count INTEGER NOT NULL DEFAULT 0,
    validation_status TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    imported_at TEXT NOT NULL,
    UNIQUE (source_kind, source_sha256)
);

CREATE TABLE IF NOT EXISTS runtime_state_snapshot (
    state_id TEXT PRIMARY KEY,
    state_kind TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT '',
    scope_id TEXT NOT NULL DEFAULT '',
    as_of_date TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (state_kind, user_id, scope_id)
);

CREATE INDEX IF NOT EXISTS idx_runtime_state_lookup
    ON runtime_state_snapshot(state_kind, user_id, scope_id, as_of_date);
