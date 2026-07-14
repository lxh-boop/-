PRAGMA foreign_keys = OFF;

DROP INDEX IF EXISTS idx_agent_steps_run_status;
DROP INDEX IF EXISTS idx_agent_tool_calls_user_tool;
DROP INDEX IF EXISTS idx_agent_sources_user_type;
DROP INDEX IF EXISTS idx_agent_sandbox_runs_user_status;

ALTER TABLE agent_steps RENAME TO agent_steps_legacy_018;
ALTER TABLE agent_tool_calls RENAME TO agent_tool_calls_legacy_018;
ALTER TABLE agent_sources RENAME TO agent_sources_legacy_018;
ALTER TABLE agent_sandbox_runs RENAME TO agent_sandbox_runs_legacy_018;

CREATE TABLE IF NOT EXISTS agent_steps (
    step_record_id TEXT,
    step_id TEXT NOT NULL,
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
    PRIMARY KEY(run_id, step_id),
    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_steps_record_id
ON agent_steps(step_record_id);

CREATE INDEX IF NOT EXISTS idx_agent_steps_run_status
ON agent_steps(run_id, status);

CREATE INDEX IF NOT EXISTS idx_agent_steps_run_started
ON agent_steps(run_id, started_at, step_record_id);

INSERT INTO agent_steps (
    step_record_id,
    step_id,
    run_id,
    parent_step_id,
    intent,
    status,
    depends_on_json,
    tool_name,
    tool_args_summary_json,
    observation_summary,
    error_type,
    error_message,
    retry_count,
    started_at,
    finished_at,
    duration_seconds,
    metadata_json
)
SELECT
    COALESCE(NULLIF(run_id, '') || ':' || NULLIF(step_id, ''), 'legacy_step_' || rowid),
    step_id,
    run_id,
    parent_step_id,
    intent,
    status,
    depends_on_json,
    tool_name,
    tool_args_summary_json,
    observation_summary,
    error_type,
    error_message,
    retry_count,
    started_at,
    finished_at,
    duration_seconds,
    metadata_json
FROM agent_steps_legacy_018
WHERE step_id IS NOT NULL AND run_id IS NOT NULL;

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
    FOREIGN KEY(run_id, step_id) REFERENCES agent_steps(run_id, step_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_user_tool
ON agent_tool_calls(user_id, tool_name, started_at);

CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_run_step
ON agent_tool_calls(run_id, step_id);

INSERT INTO agent_tool_calls (
    tool_call_id,
    run_id,
    step_id,
    user_id,
    tool_name,
    status,
    input_summary_json,
    output_summary_json,
    error_type,
    error_message,
    started_at,
    finished_at,
    duration_seconds,
    retry_count,
    metadata_json
)
SELECT
    tool_call_id,
    run_id,
    step_id,
    user_id,
    tool_name,
    status,
    input_summary_json,
    output_summary_json,
    error_type,
    error_message,
    started_at,
    finished_at,
    duration_seconds,
    retry_count,
    metadata_json
FROM agent_tool_calls_legacy_018;

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

INSERT INTO agent_sources (
    source_id,
    run_id,
    message_id,
    tool_call_id,
    user_id,
    source_type,
    source_title,
    source_time,
    database_record_id,
    file_path,
    content_hash,
    retrieved_at,
    snippet,
    metadata_json
)
SELECT
    source_id,
    run_id,
    message_id,
    tool_call_id,
    user_id,
    source_type,
    source_title,
    source_time,
    database_record_id,
    file_path,
    content_hash,
    retrieved_at,
    snippet,
    metadata_json
FROM agent_sources_legacy_018;

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
    FOREIGN KEY(run_id, step_id) REFERENCES agent_steps(run_id, step_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_sandbox_runs_user_status
ON agent_sandbox_runs(user_id, status, started_at);

CREATE INDEX IF NOT EXISTS idx_agent_sandbox_runs_run_step
ON agent_sandbox_runs(run_id, step_id);

INSERT INTO agent_sandbox_runs (
    sandbox_run_id,
    run_id,
    step_id,
    user_id,
    snapshot_id,
    code_hash,
    status,
    stdout_summary,
    result_summary_json,
    generated_files_json,
    refusal_reason,
    error_type,
    error_message,
    started_at,
    finished_at,
    duration_seconds,
    metadata_json
)
SELECT
    sandbox_run_id,
    run_id,
    step_id,
    user_id,
    snapshot_id,
    code_hash,
    status,
    stdout_summary,
    result_summary_json,
    generated_files_json,
    refusal_reason,
    error_type,
    error_message,
    started_at,
    finished_at,
    duration_seconds,
    metadata_json
FROM agent_sandbox_runs_legacy_018;

DROP TABLE agent_tool_calls_legacy_018;
DROP TABLE agent_sources_legacy_018;
DROP TABLE agent_sandbox_runs_legacy_018;
DROP TABLE agent_steps_legacy_018;

PRAGMA foreign_keys = ON;
