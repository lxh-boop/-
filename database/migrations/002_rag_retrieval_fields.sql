ALTER TABLE rag_retrieval_log ADD COLUMN decision_time TEXT;
ALTER TABLE rag_retrieval_log ADD COLUMN bm25_top_k INTEGER;
ALTER TABLE rag_retrieval_log ADD COLUMN dense_top_k INTEGER;
ALTER TABLE rag_retrieval_log ADD COLUMN rerank_top_k INTEGER;
ALTER TABLE rag_retrieval_log ADD COLUMN returned_chunk_ids TEXT;
ALTER TABLE rag_retrieval_log ADD COLUMN used_chunk_ids TEXT;

ALTER TABLE news_chunk ADD COLUMN decision_id TEXT;
