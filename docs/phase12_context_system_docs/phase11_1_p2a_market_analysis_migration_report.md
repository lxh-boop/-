# Phase 11.1-E / P2-A MarketAnalysisService Migration Report

## Scope

This stage migrated market-analysis read tools to a shared service and v2 ToolExecutor path:

- `ranking`
- `stock_analysis`
- `stock_lookup`
- `classic_stock_score`
- `classic_ranking`
- `market.compare_stocks`
- `market.get_signal_summary`

No paper-trading write path, approval path, revalidation rule, idempotency rule, RAG retriever, news retriever, or portfolio core algorithm was changed.

## Pre-change Status Table

| tool | legacy file | callers | current inputs | current outputs | current data source | through_tool_executor | planned canonical name | planned service method | planned adapter |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `ranking` | `agent/tools/ranking_tool.py` | executor, multi task executor, legacy registry | `stock_code`, `top_k`, `output_dir` | `status`, counts, `records` | `outputs/ranking_latest.csv` | partially | `market.get_ranking` | `get_ranking()` | `market_get_ranking_adapter` |
| `stock_analysis` | `agent/tools/stock_analysis_tool.py` | executor, position recommendation, legacy registry | `user_id`, `stock_code`, `top_k`, `output_dir`, `db_path` | `ToolResult.data` stock analysis fields | ranking + recommendations + portfolio state + existing news/RAG calls | partially | `market.analyze_stock` | `analyze_stock()` | `market_analyze_stock_adapter` |
| `stock_lookup` | `agent/tools/stock_lookup_tool.py` | stock analysis, legacy registry | `stock_query`, `user_id`, `output_dir` | lookup row, rank, counts | ranking + recommendations | no v2 default | `market.lookup_stock` | `lookup_stock()` | `market_lookup_stock_adapter` |
| `classic_ranking` | `app/classic_services.py` | home page classic ranking table | `output_dir`, paths, `sort_by` | DataFrame for UI | ranking + final recommendations | no v2 tool | `market.get_signal_summary` | `get_signal_summary()` | `market_signal_summary_adapter` |
| `classic_stock_score` | `agent/tool_adapter.py` style legacy stock score/explain path | legacy AgentCore/report adapter | query/model args | legacy dict | ranking files | no v2 default | `market.lookup_stock` | `lookup_stock()` / `build_score_explanation()` | `market_lookup_stock_adapter` |

## Implemented Changes

- Added `agent/services/market_analysis_service.py`.
- Added repository classes in the service file: `RankingRepository`, `StockMetadataRepository`, `PredictionRepository`, `ScoreRepository`.
- Added service methods required by the phase: `get_ranking`, `analyze_stock`, `lookup_stock`, `compare_stocks`, `get_signal_summary`, `normalize_stock_code`, `resolve_stock_name`, `load_latest_scores`, `load_model_predictions`, `build_score_explanation`.
- Added `agent/tools/market_analysis_adapters.py` with all required adapter callables and class-style aliases.
- Registered v2 tools in `agent/tool_engine.py`:
  - `market.get_ranking` with legacy `ranking`
  - `market.analyze_stock` with legacy `stock_analysis`
  - `market.lookup_stock` with legacy `stock_lookup`, `classic_stock_score`
  - `market.compare_stocks`
  - `market.get_signal_summary` with legacy `classic_ranking`
- Kept old functions as compatibility wrappers:
  - `agent/tools/ranking_tool.py::query_ranking`
  - `agent/tools/stock_lookup_tool.py::lookup_stock`
  - `agent/tools/stock_analysis_tool.py::analyze_stock`
  - `app/classic_services.py::load_classic_ranking_with_ai_adjustment`
- Extracted original stock analysis body to `agent/tools/stock_analysis_tool.py::_analyze_stock_impl` so business logic is reused instead of rewritten.
- Removed market-analysis direct fallback execution from `agent/orchestration/multi_task_executor.py`; default Agent path now resolves market analysis through v2 ToolExecutor.
- Removed unused direct market-analysis imports from `agent/executor.py` and added single-intent registered-tool handling for `stock_lookup`, `classic_stock_score`, and `classic_ranking`.
- Updated `agent/capability_index.py` so market-analysis capabilities point to v2 canonical tools.
- Added `tests/unit/test_phase11_p2a_market_analysis_service.py`.

## Unified Result Contract

The v2 market-analysis tools return read-only data containing:

- `records`
- `summary`
- `sources`
- `as_of_date`
- `not_executed: true`

The classic home-page wrapper still returns the original DataFrame shape for UI compatibility.

## Tests

Required tests:

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts` -> passed
- `py -3 -m pytest tests/unit/test_phase11_p2a_market_analysis_service.py -q` -> 6 passed
- `py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q` -> 7 passed
- `py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q` -> 6 passed
- `py -3 -m pytest tests/unit/test_phase10_goal_planning.py -q` -> 13 passed
- `py -3 -m pytest tests/unit/test_phase10_3_capability_artifacts.py -q` -> 9 passed

Additional compatibility tests:

- `py -3 -m pytest tests/unit/test_phase11_p1a_portfolio_proposal_tools.py -q` -> 6 passed
- `py -3 -m pytest tests/unit/test_classic_ui_original_and_ai_ranking.py tests/unit/test_home_page_shows_ai_adjustment_reason.py -q` -> 2 passed
- `py -3 -m pytest tests/unit/test_agent_tool_adapter.py -q` -> 7 passed

Known warnings:

- Existing `datetime.utcnow()` deprecation warning in `agent/capability_index.py`; not introduced by this stage and not blocking.

## 8501 Verification

- `http://127.0.0.1:8501/_stcore/health` -> `STATUS=200; CONTENT=ok`
- Home page:
  - no Streamlit exception
  - no mojibake detected
  - disclaimer, ranking/prediction area, paper-trading references, sidebar controls and table tools visible
- AI Agent page:
  - no Streamlit exception
  - no mojibake detected
  - chat/quick questions, confirmation/approval text, tool-related areas visible
- AI paper-trading page:
  - no Streamlit exception
  - no mojibake detected
  - account, positions, order/trade sections and `更新 AI 模拟盘` button visible
- System monitor page:
  - no Streamlit exception
  - no mojibake detected
  - monitor snapshot, alerts, layered metrics, Runtime Reliability area and `保存监控快照` button visible

## Risk Notes

- `tool_explain_stock()` remains a legacy report/AgentCore explanation path because it still contains legacy LLM fallback wording. The new Agent default market-analysis path does not depend on it.
- Existing stock analysis still calls current news/RAG tools internally; this stage intentionally did not migrate EvidenceService responsibilities.
- No MCP write tool was enabled.
- No paper-trading writer, approval, revalidate, commit, or idempotency code was relaxed.

NEXT_STAGE_ALLOWED = true
