# Phase 3 Handoff: Lightweight Agent ContextBuilder

Disclaimer: 本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## Goal

Phase 3 adds a lightweight `agent/context/` ContextBuilder for the unified Agent runtime. It collects read-only user, portfolio, conversation, memory, tool-result, and evidence context, then compresses it under a bounded token budget while preserving financial facts.

This phase does not change ranking, trading strategy, paper-trading rules, RAG retrieval rules, confirmation/revalidation boundaries, or real-trading behavior.

The four legacy Agent files were not modified:

```text
agent/portfolio_qa_agent.py
agent/event_impact_agent.py
agent/portfolio_review_agent.py
agent/model_monitor_agent.py
```

## Modified Files

- `agent/context/schemas.py`: dataclasses, token estimate, and fact extraction helpers.
- `agent/context/gatherer.py`: read-only context collection for user profile, current paper portfolio, session history, memory, tool results, evidence ids, and business constraints.
- `agent/context/selector.py`: lightweight relevance selection and history/memory caps.
- `agent/context/structurer.py`: stable section ordering and human-readable section titles.
- `agent/context/compressor.py`: deterministic compression with preservation for stock codes, dates, numbers, percentages, and source ids.
- `agent/context/builder.py`: public `build_agent_context(...)` entrypoint.
- `agent/context/__init__.py`: module exports.
- `agent/executor.py`: builds `pre_execution` context before routing and `post_observation` context after tool execution.
- `agent/runtime.py`: adds metadata merge support so run records keep ContextBuilder summaries.
- `tests/unit/test_agent_context_builder.py`: ContextBuilder and Executor integration tests.
- `tests/unit/test_agent_page_navigation.py`: updated expected top-level pages to include `系统监控`.

## Runtime Behavior

`run_agent_request(...)` now returns:

```text
context.pre_execution
context.post_observation
context_warnings
```

The full context is returned to the caller for diagnostics, but only a small summary is persisted in `agent_runs.metadata_json.context_builder`:

```text
phase
token_estimate
max_total_tokens
section_count
dropped_item_count
warning_count
preserved_fact_types
```

`pre_execution` is injected into the routing/decomposition context as `agent_context.compressed_text`. `post_observation` includes the actual tool result and evidence ids when available.

## Context Sections

The builder can emit these sections:

```text
User Context
Portfolio Context
Evidence Context
Tool Results
Business Constraints
Runtime Context
Conversation History
Agent Memory
```

User isolation rules:

- conversation history is read only after the conversation belongs to the same `user_id`
- memory is loaded through `AgentRepository.list_memory_items(user_id=...)`
- paper positions prefer `outputs/portfolio/<user_id>/paper_positions_latest.csv`; if that file is missing, database fallback is filtered by `user_id`

## Compression Rules

Compression is deterministic. It does not call an LLM and does not rewrite investment logic.

Preserved facts:

```text
stock_codes
dates
numbers and percentages
source_ids such as chunk_*, src_*, news_*, run_*
```

Default budget:

```text
max_total_tokens = 1800
```

## Test Results

Compilation:

```powershell
py -m compileall agent\context agent\executor.py agent\runtime.py
```

Result: passed.

Focused ContextBuilder and Executor tests:

```powershell
py -m pytest tests\unit\test_agent_context_builder.py -q
```

Result: `6 passed in 13.34s`.

Agent runtime, persistence, confirmation, and dual-intent regression:

```powershell
py -m pytest tests\unit\test_agent_runtime_unified.py tests\unit\test_agent_runtime_persistence.py tests\unit\test_agent_write_requires_confirmation.py tests\unit\test_agent_position_and_strategy_intents.py -q
```

Result: `8 passed in 30.28s`.

Agent wide regression:

```powershell
$files = Get-ChildItem tests\unit -Filter test_agent*.py | ForEach-Object { $_.FullName }
py -m pytest $files -q
```

First run found one stale navigation assertion from Phase 2. After updating `tests/unit/test_agent_page_navigation.py`, result: `88 passed in 67.67s`.

## Page Verification

Verified in the in-app browser against:

```text
http://127.0.0.1:8503/
```

Checked:

- home page renders ranking, backtest summary, model controls, zoom control, and top-level navigation
- `AI Agent` page renders metrics, quick questions, pending-plan panel, tools panel, and disclaimer
- clicked `查看当前模拟盘账户和持仓`; Agent completed with `agent_run_a4a34e848d57 / completed`, returned current paper positions, and showed runtime trace panels
- `系统监控` page renders total status, trade date, alert count, missing-module count, save-snapshot action, and tabs without page errors
- `AI 模拟盘` page renders current account summary, strategy boundaries, replay/audit/positions sections, and no page errors after snapshot load
- no `Traceback`, `ModuleNotFoundError`, or `NameError` was observed

## Known Limits

- ContextBuilder is intentionally lightweight and deterministic. It is not a long-term memory summarizer.
- The UI does not yet expose the raw built context. It is available in the `run_agent_request(...)` return payload and summarized in runtime metadata.
- Context injection increases decomposition prompt size by up to the configured budget. If this becomes too large, reduce `ContextBudget.max_total_tokens`.
- The builder reads current local data quality as-is. It does not create missing news, missing Dense index files, or missing portfolio history.

## Can Phase 4 Start?

Yes. Phase 3 acceptance criteria are met:

- bounded Agent context exists under `agent/context/`
- user isolation is tested
- financial entities and source ids survive compression
- Executor now builds pre-execution and post-observation context
- runtime metadata records ContextBuilder summaries
- key Agent regressions and browser checks passed

Next phase can extend memory or planner behavior on top of this module without modifying the four legacy Agent files.
