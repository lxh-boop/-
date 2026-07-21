CREATE TABLE IF NOT EXISTS strategy_implementations (
    implementation_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    proposal_version INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    implementation_type TEXT NOT NULL,
    artifact_root TEXT NOT NULL,
    implementation_hash TEXT NOT NULL,
    artifact_manifest_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(proposal_id, proposal_version),
    FOREIGN KEY (proposal_id) REFERENCES strategy_proposals(proposal_id)
);

CREATE INDEX IF NOT EXISTS idx_strategy_implementations_scope
ON strategy_implementations(user_id, account_id, conversation_id, status);
