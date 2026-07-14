CREATE TABLE IF NOT EXISTS user_profile (
    user_id TEXT PRIMARY KEY,
    age_range TEXT,
    income_level TEXT,
    available_capital REAL,
    investment_experience TEXT,
    liquidity_need TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS risk_assessment (
    assessment_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    risk_score REAL,
    risk_level TEXT,
    max_drawdown_tolerance REAL,
    single_loss_tolerance REAL,
    volatility_tolerance TEXT,
    investment_horizon TEXT,
    questionnaire_version TEXT,
    assessment_time TEXT,
    is_valid INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_risk_assessment_user ON risk_assessment(user_id);

CREATE TABLE IF NOT EXISTS investment_goal (
    goal_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    goal_type TEXT,
    target_return REAL,
    target_period TEXT,
    priority TEXT,
    capital_usage TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_investment_goal_user ON investment_goal(user_id);

CREATE TABLE IF NOT EXISTS portfolio_position (
    position_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    asset_code TEXT NOT NULL,
    asset_name TEXT,
    asset_type TEXT,
    quantity REAL,
    cost_price REAL,
    current_price REAL,
    market_value REAL,
    profit_loss REAL,
    position_ratio REAL,
    industry TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_portfolio_position_user ON portfolio_position(user_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_position_asset ON portfolio_position(asset_code);

CREATE TABLE IF NOT EXISTS trading_behavior (
    behavior_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    avg_holding_days REAL,
    turnover_rate REAL,
    avg_position_size REAL,
    preferred_industries TEXT,
    stop_loss_behavior TEXT,
    max_historical_loss REAL,
    trading_style TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stock_basic (
    stock_code TEXT PRIMARY KEY,
    stock_name TEXT,
    full_name TEXT,
    exchange TEXT,
    list_date TEXT,
    industry TEXT,
    concepts TEXT,
    main_business TEXT,
    is_st INTEGER DEFAULT 0,
    market_cap REAL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stock_alias (
    alias_id TEXT PRIMARY KEY,
    stock_code TEXT NOT NULL,
    alias_name TEXT NOT NULL,
    alias_type TEXT,
    confidence_base REAL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_stock_alias_code ON stock_alias(stock_code);
CREATE INDEX IF NOT EXISTS idx_stock_alias_name ON stock_alias(alias_name);

CREATE TABLE IF NOT EXISTS market_data_daily (
    trade_date TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    amount REAL,
    return_1d REAL,
    volatility_20d REAL,
    turnover_rate REAL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trade_date, stock_code)
);

CREATE TABLE IF NOT EXISTS model_prediction (
    prediction_id TEXT PRIMARY KEY,
    trade_date TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    model_name TEXT NOT NULL,
    pred_score REAL,
    pred_rank INTEGER,
    pred_return REAL,
    risk_score REAL,
    confidence TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_model_prediction_date ON model_prediction(trade_date);
CREATE INDEX IF NOT EXISTS idx_model_prediction_stock ON model_prediction(stock_code);

CREATE TABLE IF NOT EXISTS news_event (
    news_id TEXT PRIMARY KEY,
    title TEXT,
    summary TEXT,
    content TEXT,
    raw_file_path TEXT,
    archive_file_path TEXT,
    source TEXT,
    publish_time TEXT,
    trade_date TEXT,
    event_type TEXT,
    sentiment TEXT,
    importance_score REAL,
    is_announcement INTEGER DEFAULT 0,
    url TEXT,
    content_hash TEXT,
    retention_level TEXT DEFAULT 'hot',
    is_major_event INTEGER DEFAULT 0,
    is_used_by_agent INTEGER DEFAULT 0,
    raw_content_saved INTEGER DEFAULT 0,
    expire_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_news_event_trade_date ON news_event(trade_date);
CREATE INDEX IF NOT EXISTS idx_news_event_publish_time ON news_event(publish_time);

CREATE TABLE IF NOT EXISTS news_chunk (
    chunk_id TEXT PRIMARY KEY,
    news_id TEXT NOT NULL,
    chunk_index INTEGER,
    chunk_text TEXT NOT NULL,
    section_title TEXT,
    source TEXT,
    publish_time TEXT,
    trade_date TEXT,
    stock_code TEXT,
    industry TEXT,
    event_type TEXT,
    is_announcement INTEGER DEFAULT 0,
    used_in_decision INTEGER DEFAULT 0,
    retrieval_count INTEGER DEFAULT 0,
    importance_score REAL,
    retention_level TEXT DEFAULT 'hot',
    expire_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_news_chunk_news ON news_chunk(news_id);
CREATE INDEX IF NOT EXISTS idx_news_chunk_trade_date ON news_chunk(trade_date);
CREATE INDEX IF NOT EXISTS idx_news_chunk_stock ON news_chunk(stock_code);

CREATE TABLE IF NOT EXISTS news_embedding (
    embedding_id TEXT PRIMARY KEY,
    chunk_id TEXT NOT NULL,
    embedding_model TEXT,
    embedding_dim INTEGER,
    embedding_path TEXT,
    embedding BLOB,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS news_stock_mapping (
    mapping_id TEXT PRIMARY KEY,
    news_id TEXT NOT NULL,
    stock_code TEXT,
    stock_name TEXT,
    industry TEXT,
    concept TEXT,
    relevance_score REAL,
    impact_direction TEXT,
    impact_strength REAL,
    impact_confidence REAL,
    mapping_confidence REAL,
    mapping_method TEXT,
    evidence_text TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_news_stock_mapping_news ON news_stock_mapping(news_id);
CREATE INDEX IF NOT EXISTS idx_news_stock_mapping_stock ON news_stock_mapping(stock_code);

CREATE TABLE IF NOT EXISTS industry_event_rule (
    rule_id TEXT PRIMARY KEY,
    event_keyword TEXT,
    affected_industry TEXT,
    relation_type TEXT,
    impact_direction TEXT,
    base_strength REAL,
    description TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_rule (
    rule_id TEXT PRIMARY KEY,
    rule_name TEXT,
    rule_type TEXT,
    condition TEXT,
    action TEXT,
    priority INTEGER,
    is_active INTEGER DEFAULT 1,
    description TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_decision_log (
    decision_id TEXT PRIMARY KEY,
    user_id TEXT,
    trade_date TEXT,
    stock_code TEXT,
    original_pred_score REAL,
    original_pred_rank INTEGER,
    news_adjustment TEXT,
    risk_adjustment TEXT,
    user_constraint TEXT,
    triggered_rules TEXT,
    final_action TEXT,
    final_score REAL,
    final_reason TEXT,
    evidence_news_ids TEXT,
    evidence_chunk_ids TEXT,
    evidence_snapshot TEXT,
    retrieval_id TEXT,
    future_return_1d REAL,
    future_return_5d REAL,
    is_effective INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_decision_log_date ON agent_decision_log(trade_date);
CREATE INDEX IF NOT EXISTS idx_agent_decision_log_stock ON agent_decision_log(stock_code);
CREATE INDEX IF NOT EXISTS idx_agent_decision_log_user ON agent_decision_log(user_id);

CREATE TABLE IF NOT EXISTS backtest_evaluation (
    eval_id TEXT PRIMARY KEY,
    strategy_name TEXT,
    start_date TEXT,
    end_date TEXT,
    topk INTEGER,
    buffer INTEGER,
    annual_return REAL,
    information_ratio REAL,
    sharpe_ratio REAL,
    max_drawdown REAL,
    turnover REAL,
    win_rate REAL,
    agent_modify_count INTEGER,
    useful_modify_count INTEGER,
    false_modify_count INTEGER,
    missed_risk_count INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rag_retrieval_log (
    retrieval_id TEXT PRIMARY KEY,
    query TEXT,
    query_type TEXT,
    user_id TEXT,
    stock_code TEXT,
    trade_date TEXT,
    filters TEXT,
    bm25_results TEXT,
    dense_results TEXT,
    rerank_results TEXT,
    selected_chunk_ids TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
