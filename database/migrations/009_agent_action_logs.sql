CREATE TABLE IF NOT EXISTS agent_action_log (
    action_id TEXT PRIMARY KEY,
    session_id TEXT,
    user_id TEXT NOT NULL,
    intent TEXT,
    tool_name TEXT,
    tool_input TEXT,
    tool_output_summary TEXT,
    plan_id TEXT,
    confirmation_status TEXT,
    execution_status TEXT,
    decision_source TEXT,
    trade_date TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TEXT,
    executed_at TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_action_log_user_time
ON agent_action_log(user_id, created_at);

CREATE TABLE IF NOT EXISTS agent_tool_call_log (
    call_id TEXT PRIMARY KEY,
    session_id TEXT,
    user_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    tool_input TEXT,
    tool_output_summary TEXT,
    status TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_tool_call_log_user_time
ON agent_tool_call_log(user_id, created_at);

CREATE TABLE IF NOT EXISTS agent_confirmation_log (
    confirmation_id TEXT PRIMARY KEY,
    session_id TEXT,
    user_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    confirmation_token_hash TEXT,
    confirmation_status TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TEXT,
    expires_at TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_confirmation_log_user_plan
ON agent_confirmation_log(user_id, plan_id);
