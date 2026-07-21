ALTER TABLE paper_decision_log ADD COLUMN strategy_id TEXT NOT NULL DEFAULT '';
ALTER TABLE paper_decision_log ADD COLUMN strategy_version TEXT NOT NULL DEFAULT '';
ALTER TABLE paper_decision_log ADD COLUMN binding_id TEXT NOT NULL DEFAULT '';
ALTER TABLE paper_decision_log ADD COLUMN config_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE paper_decision_log ADD COLUMN resolved_config_json TEXT NOT NULL DEFAULT '{}';
