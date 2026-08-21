CREATE TABLE IF NOT EXISTS proposals (
    proposal_id TEXT PRIMARY KEY,
    proposal_type TEXT NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    source_run_id TEXT NOT NULL,
    source_request_id TEXT NOT NULL,
    current_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    current_payload_hash TEXT NOT NULL,
    approval_binding_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS proposal_versions (
    proposal_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    revision_reason TEXT NOT NULL DEFAULT '',
    base_version INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (proposal_id, version),
    FOREIGN KEY (proposal_id) REFERENCES proposals(proposal_id)
);

CREATE TABLE IF NOT EXISTS proposal_action_requests (
    action_request_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (proposal_id) REFERENCES proposals(proposal_id),
    UNIQUE (user_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_proposals_owner_status
    ON proposals(user_id, session_id, status, updated_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_proposals_source_identity
    ON proposals(user_id, source_run_id, source_request_id);

CREATE INDEX IF NOT EXISTS idx_proposal_action_proposal
    ON proposal_action_requests(proposal_id, created_at);
