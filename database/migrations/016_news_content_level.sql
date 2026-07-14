ALTER TABLE news_event ADD COLUMN content_level TEXT DEFAULT 'title_only';
ALTER TABLE news_chunk ADD COLUMN content_level TEXT DEFAULT 'title_only';
