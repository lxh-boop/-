CREATE TABLE IF NOT EXISTS system_monitor_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    trade_date TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT 'default',
    data_version TEXT,
    model_version TEXT,
    rag_index_version TEXT,
    run_id TEXT,
    portfolio_snapshot_id TEXT,
    overall_status TEXT NOT NULL DEFAULT 'normal',
    data_metrics_json TEXT,
    model_metrics_json TEXT,
    rag_metrics_json TEXT,
    agent_metrics_json TEXT,
    portfolio_metrics_json TEXT,
    version_info_json TEXT,
    missing_modules_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_system_monitor_snapshots_date
ON system_monitor_snapshots(trade_date, user_id);

CREATE TABLE IF NOT EXISTS system_monitor_alerts (
    alert_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT 'default',
    layer TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    metric_value REAL,
    threshold_value REAL,
    message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(snapshot_id) REFERENCES system_monitor_snapshots(snapshot_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_system_monitor_alerts_snapshot
ON system_monitor_alerts(snapshot_id, severity);
