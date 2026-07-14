# Phase 0 Handoff: Baseline Freeze

Date: 2026-07-01

Disclaimer: 本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## Modified Files

- Added `docs/IMPROVEMENT_BASELINE.md`
- Added `docs/handoff/00_BASELINE_FREEZE.md`

## Database Migration

No new migration belongs to Phase 0. Existing migrations were inspected, including Agent runtime migration `014_agent_runtime_history.sql` and news content migration `016_news_content_level.sql`.

## New Config

No Phase 0 config was added.

## Commands

```powershell
rg -n "def run_agent_request|class ToolRegistry|confirm" agent database evaluation rag portfolio pipelines -S
py -m pytest tests\unit\test_rag_dense_retriever.py tests\unit\test_news_db_sync_content_chunks.py tests\unit\test_news_rag_diagnostics.py tests\unit\test_rag_hybrid_retriever.py -q
```

## Test Result

Focused Phase 1-adjacent baseline tests passed: `7 passed`.

## Page Verification

No UI page was changed in Phase 0, so no page behavior was modified.

## Metrics

Current `data/agent_quant.db` news/RAG baseline:

- Events: 6590
- Chunks: 6590
- Duplicate chunks: 0
- Content level: `title_only` 6590
- Text length p50/p90/p95/p99: 30.0 / 48.0 / 54.0 / 71.0

## Known Limits

The live dev DB currently has no measured full-text news coverage. That is a data-source/content issue, not a paper-trading or ranking rule change.

## Can Phase 1 Start?

Yes. Phase 0 is documentation/verification only and does not modify business logic.
