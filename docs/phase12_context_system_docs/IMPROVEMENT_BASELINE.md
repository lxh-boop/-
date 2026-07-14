# Financial Agent Improvement Baseline

Snapshot date: 2026-07-01

Disclaimer: 本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## Scope

This document freezes the current implementation before continuing the staged financial Agent improvement route. Phase 0 is documentation and verification only; it does not change trading strategy, paper-trading rules, model ranking rules, or the four legacy Agent files.

Do not modify in this route:

- `agent/portfolio_qa_agent.py`
- `agent/event_impact_agent.py`
- `agent/portfolio_review_agent.py`
- `agent/model_monitor_agent.py`

## Current Entrypoints

- App: `app.py`
- Daily update: `daily_incremental_update.py`
- Agent runtime entry: `agent/executor.py::run_agent_request`
- Multi-intent executor: `agent/orchestration/multi_task_executor.py`
- Tool registry: `agent/tools/tool_registry.py`
- Confirmation gateway: `agent/session/confirmation_manager.py`
- News sync: `news_db_sync.py`
- News cache fetch/normalization: `news_data.py`
- RAG retrieval: `rag/bm25_retriever.py`, `rag/dense_retriever.py`, `rag/hybrid_retriever.py`, `rag/reranker.py`
- Agent harness: `evaluation/agent_harness/`
- News RAG diagnostics: `evaluation/news_rag_diagnostics.py`

## Current Database Tables

Key tables are initialized through `database/migrations/*.sql`.

- News/RAG: `news_event`, `news_chunk`, `news_embedding`, `news_stock_mapping`, `rag_retrieval_log`
- Agent runtime: `conversations`, `messages`, `agent_runs`, `agent_steps`, `agent_tool_calls`, `agent_sources`, `agent_sandbox_runs`
- Action safety: `action_proposals`, `action_approvals`, `action_commits`, `agent_action_log`, `agent_confirmation_log`
- Memory: `conversation_summaries`, `memory_items`, `memory_links`, `user_feedback`
- Paper trading: `paper_account`, `paper_order`, `paper_decision_log`, `paper_cash_flow`, `paper_nav_history`, `paper_account_snapshot`

Latest migration relevant to Phase 1:

- `database/migrations/016_news_content_level.sql`

Latest migration relevant to Phase 2:

- `database/migrations/017_system_monitor.sql`

## Current Index Paths

- BM25 index: `outputs/rag_indexes/news_bm25.pkl`
- Dense index: `outputs/rag_indexes/news_dense.pkl`
- Diagnostic reports may be written under `runtime/` or a caller-provided `--report-path`.

## Current News/RAG Data Baseline

Observed against `data/agent_quant.db` on 2026-07-01:

- `event_count`: 6590
- `chunk_count`: 6590
- `event_to_chunk_distribution`: min 1, max 1, avg 1.0
- `text_length_p50`: 30.0
- `text_length_p90`: 48.0
- `text_length_p95`: 54.0
- `text_length_p99`: 71.0
- `duplicate_chunk_count`: 0
- `empty_chunk_count`: 0
- `content_level_distribution`: `{"title_only": 6590}`

Interpretation: the current live development database is mostly title-only news/announcement data. This is now visible and measurable; it should not be treated as full-text evidence.

## Current Dense State

Before this phase, `sentence-transformers` was not installed and Dense retrieval silently degraded to empty results. Phase 1 adds explicit status fields and the dependency entry.

Local verification after installation:

- `embedding_model_name`: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- `embedding_dimension`: 384
- `index_version`: `dense-v1:<model>:dim384:chunksN:<hash>`
- Strict diagnostic on a temporary full-text fixture passed with Dense enabled.

## Current Test Baseline

Commands run during Phase 0/1:

```powershell
py -m compileall rag\dense_retriever.py rag\hybrid_retriever.py news_db_sync.py evaluation\news_rag_diagnostics.py scripts\resync_news_rag.py
py -m pytest tests\unit\test_rag_dense_retriever.py tests\unit\test_news_db_sync_content_chunks.py tests\unit\test_news_rag_diagnostics.py tests\unit\test_rag_hybrid_retriever.py -q
$rag = Get-ChildItem -Path tests\unit -Filter 'test_rag_*.py' | ForEach-Object { $_.FullName }; $news = Get-ChildItem -Path tests\unit -Filter 'test_news_*.py' | ForEach-Object { $_.FullName }; py -m pytest @rag @news -q
```

Results:

- Focused Phase 1 tests: `7 passed`
- RAG/News regression: `34 passed, 2 warnings`
- Warnings are existing pandas concat `FutureWarning` in `news_data.py`.

## Known Limits

- The current live development DB still contains title-only news. Real full-text coverage depends on the upstream news source returning summaries/content.
- Cross-Encoder reranker may require a Hugging Face model download on first use.
- Phase 2 monitoring tables and UI are now implemented. Current local monitor status is `critical` mainly because `full_text_ratio=0.0`, `rag_empty_rate=0.8296`, and stored portfolio drawdown breaches the first threshold.

## Phase 2 Verification Summary

Added handoff:

- `docs/handoff/02_SYSTEM_MONITORING.md`

Commands run:

```powershell
py -m pytest tests\unit\test_system_monitor.py tests\unit\test_app_top_level_pages.py -q
py -m pytest tests\unit\test_database_schema.py tests\unit\test_database_repositories.py tests\unit\test_rag_dense_retriever.py tests\unit\test_rag_hybrid_retriever.py -q
py -m pytest tests\unit\test_agent_runtime_persistence.py tests\unit\test_agent_runtime_unified.py tests\unit\test_agent_write_requires_confirmation.py -q
```

Results:

- Phase 2 focused tests: `7 passed`
- Database/RAG regression: `8 passed`
- Agent runtime safety regression: `4 passed`

The in-app browser verified `http://127.0.0.1:8503/` with `系统监控`, `首页 / 预测排名`, `AI 模拟盘`, and `AI Agent` top-level pages. No page Traceback was observed.

## Phase 3 Verification Summary

Added handoff:

- `docs/handoff/03_CONTEXT_BUILDER.md`

Commands run:

```powershell
py -m compileall agent\context agent\executor.py agent\runtime.py
py -m pytest tests\unit\test_agent_context_builder.py -q
py -m pytest tests\unit\test_agent_runtime_unified.py tests\unit\test_agent_runtime_persistence.py tests\unit\test_agent_write_requires_confirmation.py tests\unit\test_agent_position_and_strategy_intents.py -q
$files = Get-ChildItem tests\unit -Filter test_agent*.py | ForEach-Object { $_.FullName }
py -m pytest $files -q
```

Results:

- ContextBuilder focused tests: `6 passed`
- Agent runtime and safety regression: `8 passed`
- Agent wide regression: `88 passed`

The in-app browser verified `http://127.0.0.1:8503/`. `AI Agent` completed a read-only paper-portfolio quick question and produced `agent_run_a4a34e848d57 / completed`; `系统监控` and `AI 模拟盘` also rendered without `Traceback`, `ModuleNotFoundError`, or `NameError`.

## Phase 4 Verification Summary

Added handoff:

- `docs/handoff/04_LAYERED_MEMORY.md`

Commands run:

```powershell
py -m compileall agent\memory.py database\repositories\agent_repository.py
py -m compileall agent\memory.py agent\context\gatherer.py agent\context
py -m pytest tests\unit\test_agent_layered_memory.py -q
py -m pytest tests\unit\test_agent_layered_memory.py tests\unit\test_agent_context_builder.py tests\unit\test_agent_runtime_unified.py tests\unit\test_agent_runtime_persistence.py tests\unit\test_agent_write_requires_confirmation.py -q
$files = Get-ChildItem tests\unit -Filter test_agent*.py | ForEach-Object { $_.FullName }
py -m pytest $files -q
```

Results:

- Layered Memory focused tests: `8 passed`
- Memory + ContextBuilder + Agent safety regression: `18 passed`
- Agent wide regression: `96 passed`

The in-app browser verified `http://127.0.0.1:8503/`. `AI Agent` completed a read-only paper-portfolio quick question and produced `agent_run_05705fe532dc / completed`; no app `Traceback`, `ModuleNotFoundError`, or `NameError` was observed.

## Phase 5 Verification Summary

Added handoff:

- `docs/handoff/05_AGENT_HARNESS_QUALITY.md`

Commands run:

```powershell
py -m compileall evaluation\agent_harness
py -m pytest tests\unit\test_agent_harness_quality.py -q
py -m pytest tests\unit\test_agent_harness_runner.py -q
py -m pytest tests\unit\test_agent_harness_quality.py tests\unit\test_agent_harness_runner.py tests\unit\test_agent_runtime_unified.py tests\unit\test_agent_write_requires_confirmation.py -q
$files = Get-ChildItem tests\unit -Filter test_agent*.py | ForEach-Object { $_.FullName }
py -m pytest $files -q
py -m evaluation.agent_harness.cli --cases data\evaluation\agent_harness_cases.jsonl --output-dir runtime\phase5_cli --no-export
```

Results:

- Harness quality tests: `4 passed`
- Existing Harness runner: `2 passed`
- Harness + Agent safety regression: `8 passed`
- Agent wide regression: `100 passed`
- Harness CLI: `case_pass_rate=1.0`, `agent_composite_score=1.0`

The in-app browser verified `http://127.0.0.1:8503/`. `AI Agent` control center, quick questions, and disclaimers rendered without app `Traceback`, `ModuleNotFoundError`, or `NameError`.

## Phase 6 Verification Summary

Added handoff:

- `docs/handoff/06_RUNTIME_RELIABILITY_FAULT_INJECTION.md`

Commands run:

```powershell
py -m compileall agent\runtime_reliability.py evaluation\runtime_fault_injection.py scripts\run_runtime_fault_injection.py database\sqlite_store.py
py -m pytest tests\unit\test_runtime_reliability_fault_injection.py -q
py scripts\run_runtime_fault_injection.py --task-count 20 --report-path runtime\phase6_fault_injection\report.json
py -m pytest tests\unit\test_runtime_reliability_fault_injection.py tests\unit\test_agent_multi_task_async.py tests\unit\test_agent_idempotency.py tests\unit\test_agent_write_requires_confirmation.py tests\unit\test_agent_paper_trade_execution.py -q
py -m pytest tests\unit\test_database_schema.py tests\unit\test_database_repositories.py tests\unit\test_agent_runtime_persistence.py -q
$files = Get-ChildItem tests\unit -Filter test_agent*.py | ForEach-Object { $_.FullName }
py -m pytest $files -q
```

Results:

- Runtime reliability tests: `7 passed`
- Fault-injection CLI: `all_passed=true`
- Agent reliability/safety regression: `20 passed`
- Database regression: `7 passed`
- Agent wide regression: `100 passed`

The in-app browser verified `http://127.0.0.1:8503/`. `AI Agent` control center, scheduler quick question, and disclaimers rendered without app `Traceback`, `ModuleNotFoundError`, or `NameError`.

## Phase 7 Verification Summary

Added handoff:

- `docs/handoff/07_DECISION_ATTRIBUTION.md`

Commands run:

```powershell
py -m compileall portfolio\decision_attribution.py app\pages\ai_paper_trading.py portfolio\__init__.py
py -m pytest tests\unit\test_decision_attribution.py -q
py -m pytest tests\unit\test_decision_attribution.py tests\unit\test_scoring_explain.py tests\unit\test_daily_audit_log_contains_weight_rounds.py tests\unit\test_paper_trading_pipeline.py tests\unit\test_paper_trading_uses_original_and_ai_adjusted_signals.py -q
py -m pytest tests\unit\test_ai_paper_trading_not_in_sidebar.py tests\unit\test_decision_attribution.py -q
py -m pytest tests\unit -q
```

Results:

- Decision attribution tests: `4 passed`
- Paper-trading/explanation regression: `9 passed`
- Navigation/attribution regression: `5 passed`
- Full unit regression: `541 passed`, `2 warnings`

The Phase 7 attribution service is read-only. It explains persisted final recommendations, paper decisions, and execution diagnostics; it does not recompute ranking, AI adjustment, RAG, target weights, orders, or paper-trading results.

## Forbidden Changes

Still forbidden in this route:

- Reintroducing old local MLP training/prediction/storage.
- Changing original ranking, Top10/Top15 buffer, target allocation, minimum cash ratio, single-stock cap, lot-size rules, transaction cost rules, or confirmation/revalidation safety boundaries.
- Connecting to real trading.
