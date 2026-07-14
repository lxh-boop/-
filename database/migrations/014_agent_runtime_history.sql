CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    language TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_message_at TEXT,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_time
ON conversations(user_id, updated_at);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    language TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    token_estimate INTEGER DEFAULT 0,
    metadata_json TEXT,
    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_time
ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id TEXT PRIMARY KEY,
    conversation_id TEXT,
    user_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT,
    error_type TEXT,
    error_message TEXT,
    metadata_json TEXT,
    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_user_status
ON agent_runs(user_id, status, created_at);

CREATE TABLE IF NOT EXISTS agent_steps (
    step_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    parent_step_id TEXT,
    intent TEXT,
    status TEXT NOT NULL,
    depends_on_json TEXT,
    tool_name TEXT,
    tool_args_summary_json TEXT,
    observation_summary TEXT,
    error_type TEXT,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    started_at TEXT,
    finished_at TEXT,
    duration_seconds REAL DEFAULT 0,
    metadata_json TEXT,
    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_steps_run_status
ON agent_steps(run_id, status);

CREATE TABLE IF NOT EXISTS agent_tool_calls (
    tool_call_id TEXT PRIMARY KEY,
    run_id TEXT,
    step_id TEXT,
    user_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL,
    input_summary_json TEXT,
    output_summary_json TEXT,
    error_type TEXT,
    error_message TEXT,
    started_at TEXT,
    finished_at TEXT,
    duration_seconds REAL DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    metadata_json TEXT,
    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE SET NULL,
    FOREIGN KEY(step_id) REFERENCES agent_steps(step_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_user_tool
ON agent_tool_calls(user_id, tool_name, started_at);

CREATE TABLE IF NOT EXISTS agent_sources (
    source_id TEXT PRIMARY KEY,
    run_id TEXT,
    message_id TEXT,
    tool_call_id TEXT,
    user_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_title TEXT,
    source_time TEXT,
    database_record_id TEXT,
    file_path TEXT,
    content_hash TEXT,
    retrieved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    snippet TEXT,
    metadata_json TEXT,
    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE SET NULL,
    FOREIGN KEY(message_id) REFERENCES messages(message_id) ON DELETE SET NULL,
    FOREIGN KEY(tool_call_id) REFERENCES agent_tool_calls(tool_call_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_sources_user_type
ON agent_sources(user_id, source_type, retrieved_at);

CREATE TABLE IF NOT EXISTS agent_sandbox_runs (
    sandbox_run_id TEXT PRIMARY KEY,
    run_id TEXT,
    step_id TEXT,
    user_id TEXT NOT NULL,
    snapshot_id TEXT,
    code_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    stdout_summary TEXT,
    result_summary_json TEXT,
    generated_files_json TEXT,
    refusal_reason TEXT,
    error_type TEXT,
    error_message TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    duration_seconds REAL DEFAULT 0,
    metadata_json TEXT,
    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE SET NULL,
    FOREIGN KEY(step_id) REFERENCES agent_steps(step_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_sandbox_runs_user_status
ON agent_sandbox_runs(user_id, status, started_at);

CREATE TABLE IF NOT EXISTS action_proposals (
    plan_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    run_id TEXT,
    operation_type TEXT NOT NULL,
    snapshot_id TEXT,
    business_state_version TEXT,
    plan_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT,
    before_state_summary_json TEXT,
    proposed_changes_json TEXT,
    after_state_preview_json TEXT,
    warnings_json TEXT,
    validation_results_json TEXT,
    requires_confirmation INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT,
    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_action_proposals_user_status
ON action_proposals(user_id, status, created_at);

CREATE TABLE IF NOT EXISTS action_approvals (
    approval_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    plan_hash TEXT NOT NULL,
    snapshot_id TEXT,
    business_state_version TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    used_at TEXT,
    expires_at TEXT,
    metadata_json TEXT,
    FOREIGN KEY(plan_id) REFERENCES action_proposals(plan_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_action_approvals_plan_status
ON action_approvals(plan_id, status);

CREATE TABLE IF NOT EXISTS action_commits (
    commit_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    approval_id TEXT,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL,
    idempotency_key TEXT,
    before_state_hash TEXT,
    after_state_hash TEXT,
    result_summary_json TEXT,
    error_type TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    committed_at TEXT,
    metadata_json TEXT,
    FOREIGN KEY(plan_id) REFERENCES action_proposals(plan_id) ON DELETE CASCADE,
    FOREIGN KEY(approval_id) REFERENCES action_approvals(approval_id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_action_commits_idempotency
ON action_commits(idempotency_key);

CREATE TABLE IF NOT EXISTS conversation_summaries (
    summary_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    covered_message_count INTEGER DEFAULT 0,
    token_estimate INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT,
    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_conversation_summaries_user_status
ON conversation_summaries(user_id, status, updated_at);

CREATE TABLE IF NOT EXISTS memory_items (
    memory_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    conversation_id TEXT,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    topics_json TEXT,
    stock_codes_json TEXT,
    company_names_json TEXT,
    industries_json TEXT,
    importance REAL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    source_type TEXT,
    source_id TEXT,
    valid_from TEXT,
    valid_until TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    supersedes_memory_id TEXT,
    metadata_json TEXT,
    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_items_user_type_status
ON memory_items(user_id, memory_type, status, updated_at);

CREATE TABLE IF NOT EXISTS memory_links (
    link_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    linked_type TEXT NOT NULL,
    linked_id TEXT NOT NULL,
    relation TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT,
    FOREIGN KEY(memory_id) REFERENCES memory_items(memory_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_links_memory
ON memory_links(memory_id, linked_type);

CREATE TABLE IF NOT EXISTS user_feedback (
    feedback_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    conversation_id TEXT,
    run_id TEXT,
    message_id TEXT,
    feedback_type TEXT NOT NULL,
    rating INTEGER,
    comment TEXT,
    source_id TEXT,
    tool_name TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT,
    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE SET NULL,
    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE SET NULL,
    FOREIGN KEY(message_id) REFERENCES messages(message_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_user_feedback_user_type
ON user_feedback(user_id, feedback_type, created_at);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    run_id TEXT,
    artifact_type TEXT NOT NULL,
    path TEXT NOT NULL,
    content_hash TEXT,
    size_bytes INTEGER DEFAULT 0,
    retention_policy TEXT DEFAULT 'standard',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT,
    metadata_json TEXT,
    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_artifacts_user_type
ON artifacts(user_id, artifact_type, created_at);
