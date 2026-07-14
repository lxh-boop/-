# Phase 11.1 / P2-B EvidenceService Migration Report

## Scope

This stage migrated news, RAG, and read-only evidence tools behind a unified
EvidenceService without changing the news download pipeline, RAG retrieval
algorithm, ranking algorithm, paper-trading logic, or approval/revalidate/commit
boundary.

## Pre-change Status

| Area | Before | Risk | Stage action |
| --- | --- | --- | --- |
| `stock_news` | `agent/tools/stock_news_tool.py::query_stock_news` called the database repository directly. | Agent default path could bypass a unified evidence contract. | Kept the function as a compatibility wrapper and routed it through `EvidenceService.search_news()`. |
| `stock_rag` | `agent/tools/stock_rag_tool.py::query_stock_rag` called `rag_retriever.retrieve_stock_context()` directly. | Agent default path could bypass a unified evidence contract and had inconsistent empty/error shapes. | Kept the function as a compatibility wrapper and routed it through `EvidenceService.search_rag()`. |
| MCP read-only evidence | `mcp.readonly.invoke` called the MCP bridge directly. | Read-only MCP output was not normalized with local evidence sources. | Added `EvidenceService.get_mcp_readonly_evidence()` and kept write tools blocked. |
| ToolExecutor registry | Canonical tools were market-prefixed legacy entries for news/RAG. | Evidence tools were mixed with market-analysis responsibilities. | Registered v2 evidence canonical names with legacy aliases. |
| Multi-task executor | Had direct fallback branches for `stock_news` and `stock_rag`. | Agent could bypass v2 ToolExecutor. | Removed direct fallback execution and expanded read-intent/capability filters for evidence tools. |
| Legacy adapter functions | `agent/tool_adapter.py` still had older general news/RAG helpers. | UI/old AgentCore compatibility still needed them. | Preserved them and added source formatting when possible. |

## Implemented Changes

- Added `agent/services/evidence_service.py`.
  - Classes: `SourceFormatter`, `NewsRepository`, `RagRepository`, `McpEvidenceClient`, `EvidenceService`.
  - Singleton: `evidence_service`.
  - Methods: `search_news`, `search_rag`, `get_stock_evidence`, `get_market_evidence`, `get_mcp_readonly_evidence`, `merge_evidence`, `deduplicate_sources`, `rank_evidence`, `format_sources`, `build_evidence_summary`.
- Added `agent/tools/evidence_adapters.py`.
  - Adapter callables and class-style aliases:
    `EvidenceSearchNewsAdapter`, `EvidenceSearchRagAdapter`,
    `EvidenceGetStockEvidenceAdapter`, `EvidenceGetMarketEvidenceAdapter`,
    `EvidenceMcpReadonlyAdapter`.
- Updated `agent/tool_engine.py`.
  - Registered:
    - `evidence.search_news` with legacy aliases `stock_news`, `news_search`
    - `evidence.search_rag` with legacy aliases `stock_rag`, `rag_search`
    - `evidence.get_stock_evidence`
    - `evidence.get_market_evidence`
    - `evidence.mcp_readonly_evidence` with legacy alias `mcp_market_risk_summary`
  - Routed `mcp.readonly.invoke` through the EvidenceService adapter while keeping the existing MCP bridge and read-only restrictions.
- Updated compatibility wrappers.
  - `agent/tools/stock_news_tool.py::query_stock_news`
  - `agent/tools/stock_rag_tool.py::query_stock_rag`
  - Both preserve old top-level fields such as `events`, `mappings`, `event_count`, and `chunks`.
- Updated execution paths.
  - `agent/orchestration/multi_task_executor.py` no longer has direct `stock_news` / `stock_rag` fallback execution.
  - `agent/executor.py` no longer imports news/RAG tools directly.
  - `agent/capability_index.py` maps evidence capabilities to v2 canonical tools.
- Added `tests/unit/test_phase11_p2b_evidence_service.py`.

## Unified Result Contract

Evidence tools return read-only results containing:

- `query`
- `stock_code`
- `records`
- `summary`
- `sources`
- `evidence_count`
- `as_of_date`
- `not_executed`
- `mutation_performed: false`

RAG-unavailable and invalid-input cases return safe structured empty results
instead of raising UI-breaking exceptions.

## Tests

Required tests:

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts` -> passed
- `py -3 -m pytest tests/unit/test_phase11_p2b_evidence_service.py -q` -> 6 passed
- `py -3 -m pytest tests/unit/test_mcp_phase9_financial_evidence.py -q` -> 17 passed
- `py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q` -> 7 passed
- `py -3 -m pytest tests/unit/test_phase10_goal_planning.py -q` -> 13 passed
- `py -3 -m pytest tests/unit/test_phase10_3_capability_artifacts.py -q` -> 9 passed

Additional regression tests:

- `py -3 -m pytest tests/unit/test_phase11_p2a_market_analysis_service.py -q` -> 6 passed
- `py -3 -m pytest tests/unit/test_phase11_p1b_system_aux_tools.py -q` -> 8 passed
- `py -3 -m pytest tests/unit/test_agent_stock_analysis.py -q` -> 1 passed
- `py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q` -> 6 passed

Known warnings:

- Existing `datetime.utcnow()` deprecation warnings in prior Phase 10/11 tests.
  They were not introduced by this stage and did not fail the run.

## 8501 Verification

- `http://127.0.0.1:8501/_stcore/health` -> `STATUS=200; CONTENT=ok`

Manual browser checks:

- Home / prediction page:
  - no Streamlit exception
  - no mojibake detected
  - ranking/prediction area, model-management controls, manual daily-update button,
    chart/table controls, and sidebar settings visible
- AI Agent page:
  - no Streamlit exception
  - no mojibake detected
  - chat controls, quick-question buttons, send control, and existing trace/details
    sections visible
- AI paper-trading page:
  - no Streamlit exception
  - no mojibake detected
  - user profile controls, account summary, holdings/account/order/risk signals,
    and `Update AI paper trading` control visible
- System monitor page:
  - no Streamlit exception
  - no mojibake detected
  - total status, monitor snapshot button, alerts/layered metrics tables, and
    Runtime Reliability section visible

## Risk Notes

- No write tool was added to MCP. MCP writes remain blocked by the existing
  read-only registry and were covered by the P2-B tests.
- News download, RAG indexing/retrieval, and MCP bridge internals were not
  rewritten; this stage only added service/adapters and routing normalization.
- `agent/tool_adapter.py` legacy general-query functions remain compatibility
  paths because they are not stock-code-specific. They now format evidence
  sources when available.
- Paper-trading writers, approval, revalidate, commit, and idempotency code were
  not changed.

NEXT_STAGE_ALLOWED = true
