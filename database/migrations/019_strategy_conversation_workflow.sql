CREATE TABLE IF NOT EXISTS strategy_proposals (
    proposal_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    original_request TEXT NOT NULL,
    current_version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_strategy_proposals_scope
ON strategy_proposals(user_id, account_id, conversation_id, status, updated_at);

CREATE TABLE IF NOT EXISTS strategy_proposal_versions (
    proposal_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    base_strategy_id TEXT NOT NULL,
    base_strategy_version TEXT NOT NULL,
    proposal_json TEXT NOT NULL,
    user_feedback TEXT,
    change_summary TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_run_id TEXT,
    PRIMARY KEY (proposal_id, version),
    FOREIGN KEY (proposal_id) REFERENCES strategy_proposals(proposal_id)
);

CREATE INDEX IF NOT EXISTS idx_strategy_proposal_versions_created
ON strategy_proposal_versions(proposal_id, created_at);
