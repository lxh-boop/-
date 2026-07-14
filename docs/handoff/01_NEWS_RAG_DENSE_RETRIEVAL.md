# Phase 1 Handoff: News RAG and Dense Retrieval

Date: 2026-07-01

Disclaimer: 本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## Modified Files

- `news_db_sync.py`
- `evaluation/news_rag_diagnostics.py`
- `rag/dense_retriever.py`
- `rag/hybrid_retriever.py`
- `requirements.txt`
- `scripts/resync_news_rag.py`
- `tests/unit/test_rag_dense_retriever.py`
- `tests/unit/test_news_db_sync_content_chunks.py`
- `tests/unit/test_news_rag_diagnostics.py`

The four legacy Agent files were not modified.

## Database Migration

No new Phase 1 migration was required because `database/migrations/016_news_content_level.sql` already adds:

```sql
ALTER TABLE news_event ADD COLUMN content_level TEXT DEFAULT 'title_only';
ALTER TABLE news_chunk ADD COLUMN content_level TEXT DEFAULT 'title_only';
```

## New Config / Dependency

- Added `sentence-transformers` to `requirements.txt`.
- Dense default model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.
- Dense status now records `embedding_model_name`, `embedding_dimension`, `index_version`, `load_error`, and `fallback_reason`.

## Commands

Resync from existing cache, clean old chunks, rebuild indexes, and run diagnostics:

```powershell
py scripts\resync_news_rag.py --from-cache --db-path data\agent_quant.db --output-dir outputs --query "000001 news risk" --stock-code 000001 --decision-time "2026-06-24 14:30:00"
```

Run an isolated CSV fixture without touching the main database:

```powershell
py scripts\resync_news_rag.py --events-csv runtime\phase1_news_rag_cli\events.csv --db-path runtime\phase1_news_rag_cli\agent_quant.db --output-dir runtime\phase1_news_rag_cli\outputs --query "000001 Ping An Bank profit risk" --stock-code 000001 --decision-time "2026-06-24 14:30:00" --require-dense --report-path runtime\phase1_news_rag_cli\report.json
```

Fetch/resync for a date range:

```powershell
py scripts\resync_news_rag.py --start-date 20260601 --end-date 20260630 --db-path data\agent_quant.db --output-dir outputs --query "000001 news risk" --stock-code 000001 --decision-time "2026-06-24 14:30:00"
```

Strict Dense acceptance mode:

```powershell
py -m evaluation.news_rag_diagnostics --db-path data\agent_quant.db --output-dir outputs --query "000001 news risk" --stock-code 000001 --decision-time "2026-06-24 14:30:00" --require-dense
```

## Test Results

```text
compileall: passed
focused tests: 7 passed
RAG/News regression: 34 passed, 2 warnings
strict temporary Dense diagnostic: 10 checks passed, failed 0, pass_rate 1.0
strict CLI fixture diagnostic: 10 checks passed, failed 0, pass_rate 1.0
```

The warnings are existing pandas concat `FutureWarning` messages in `news_data.py`.

## Page Verification

No Streamlit page was changed in Phase 1. The validation target is the RAG/news backend and command-line diagnostics.

## Metrics

Temporary strict full-text diagnostic:

- `content_level_distribution`: `{"full_text": 2}`
- `duplicate_chunk_count`: 0
- `future_news_filtered_count`: 1
- Dense available: true
- Dense dimension: 384
- Checks: future leakage, stock filter, duplicate chunks, traceability, content integrity, BM25, Dense, Hybrid/Reranker all passed.

Main development DB baseline remains:

- `event_count`: 6590
- `chunk_count`: 6590
- `content_level_distribution`: `{"title_only": 6590}`

## Known Limits

- Main DB still needs a real full-text resync from upstream data sources to improve evidence quality.
- First use of Dense/Reranker may download Hugging Face model weights and can be slow on Windows.
- Diagnostics are engineering checks; they do not replace Ragas quality gates or financial correctness review.

## Can Phase 2 Start?

Yes for code readiness. For data-quality readiness, run a real news resync and confirm `full_text`/`summary` ratios improve beyond the current title-only baseline.
