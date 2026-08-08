ALTER TABLE news_chunk ADD COLUMN title TEXT;
ALTER TABLE news_chunk ADD COLUMN stock_codes_json TEXT;
ALTER TABLE news_chunk ADD COLUMN entities_json TEXT;
ALTER TABLE news_chunk ADD COLUMN metadata_json TEXT;

CREATE INDEX IF NOT EXISTS idx_news_chunk_publish_time ON news_chunk(publish_time);
CREATE INDEX IF NOT EXISTS idx_news_chunk_industry ON news_chunk(industry);
CREATE INDEX IF NOT EXISTS idx_news_chunk_event_type ON news_chunk(event_type);
