CREATE TABLE IF NOT EXISTS strategy_registry (
    strategy_id TEXT NOT NULL,
    version TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    module_path TEXT NOT NULL,
    class_name TEXT NOT NULL,
    config_schema_json TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    code_hash TEXT,
    validation_status TEXT,
    backtest_status TEXT,
    enabled_for_paper_trading INTEGER NOT NULL DEFAULT 0,
    enabled_at TEXT,
    disabled_at TEXT,
    archived_at TEXT,
    previous_strategy_id TEXT,
    previous_version TEXT,
    metadata_json TEXT,
    PRIMARY KEY (strategy_id, version)
);

CREATE INDEX IF NOT EXISTS idx_strategy_registry_status
ON strategy_registry(status, enabled_for_paper_trading, created_at);
