from __future__ import annotations

import sqlite3
from pathlib import Path

from config import DATA_DIR


NEWS_MAPPING_DB_PATH = Path(DATA_DIR) / "news_mapping.db"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stock_master (
    code TEXT PRIMARY KEY,
    ts_code TEXT,
    name TEXT,
    fullname TEXT,
    industry TEXT,
    area TEXT,
    list_date TEXT,
    aliases TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS stock_alias (
    alias TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    source TEXT,
    confidence REAL,
    updated_at TEXT,
    PRIMARY KEY (alias, code)
);

CREATE INDEX IF NOT EXISTS idx_stock_alias_alias
ON stock_alias(alias);

CREATE INDEX IF NOT EXISTS idx_stock_alias_code
ON stock_alias(code);

CREATE TABLE IF NOT EXISTS concept_stock_map (
    concept TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    relation_type TEXT,
    confidence REAL,
    evidence TEXT,
    source TEXT,
    updated_at TEXT,
    PRIMARY KEY (concept, code, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_concept_stock_map_concept
ON concept_stock_map(concept);

CREATE TABLE IF NOT EXISTS news_items (
    news_id TEXT PRIMARY KEY,
    date TEXT,
    publish_time TEXT,
    title TEXT,
    content TEXT,
    source TEXT,
    url TEXT,
    raw_text_hash TEXT,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_news_items_date
ON news_items(date);

CREATE UNIQUE INDEX IF NOT EXISTS idx_news_items_hash
ON news_items(raw_text_hash);

CREATE TABLE IF NOT EXISTS news_stock_links (
    news_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    link_type TEXT,
    confidence REAL,
    reason TEXT,
    evidence TEXT,
    mapper TEXT,
    status TEXT,
    created_at TEXT,
    PRIMARY KEY (news_id, code, mapper)
);

CREATE INDEX IF NOT EXISTS idx_news_stock_links_news
ON news_stock_links(news_id);

CREATE INDEX IF NOT EXISTS idx_news_stock_links_code
ON news_stock_links(code);

CREATE INDEX IF NOT EXISTS idx_news_stock_links_status
ON news_stock_links(status);

CREATE TABLE IF NOT EXISTS mapping_feedback (
    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id TEXT,
    code TEXT,
    old_status TEXT,
    new_status TEXT,
    comment TEXT,
    created_at TEXT
);
"""


def get_connection(db_path: str | Path = NEWS_MAPPING_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path = NEWS_MAPPING_DB_PATH) -> Path:
    path = Path(db_path)
    with get_connection(path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    return path


if __name__ == "__main__":
    created = init_db()
    print(f"news mapping db ready: {created}")
