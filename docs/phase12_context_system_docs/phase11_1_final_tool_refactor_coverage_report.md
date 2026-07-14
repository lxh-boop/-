# Phase 11.1 Final Tool Refactor Coverage Report

## Scope

This report closes the staged Phase 11.1 tool refactor sequence:

1. P1-B system auxiliary tools and MCP base migration.
2. P2-A MarketAnalysisService convergence.
3. P2-B EvidenceService and news RAG convergence.
4. P2-C PortfolioService and PortfolioRiskService extraction.
5. Final legacy cleanup, CapabilityIndex, artifact, and coverage validation.

No business algorithm, paper trading core rule, approval boundary, revalidate step, idempotency guard, or MCP write boundary was intentionally changed.

## Stage Gate Summary

| Stage | Report | Result |
| --- | --- | --- |
| Phase 11.1 inventory | `docs/phase11_1_tool_refactor_inventory_report.md` | Completed |
| P0 write tool closed loop | `docs/phase11_1_p0_write_tool_migration_report.md` | Completed |
| P1-A portfolio proposal tools | `docs/phase11_1_p1a_portfolio_proposal_tool_migration_report.md` | Completed |
| P1-B system auxiliary tools | `docs/phase11_1_p1b_system_aux_tool_migration_report.md` | NEXT_STAGE_ALLOWED = true |
| P2-A market analysis service | `docs/phase11_1_p2a_market_analysis_migration_report.md` | NEXT_STAGE_ALLOWED = true |
| P2-B evidence service | `docs/phase11_1_p2b_evidence_service_migration_report.md` | NEXT_STAGE_ALLOWED = true |
| P2-C portfolio/risk service | `docs/phase11_1_p2c_portfolio_risk_service_migration_report.md` | NEXT_STAGE_ALLOWED = true |

## Final Coverage Metrics

| Metric | Value |
| --- | ---: |
| Discovered tool-like entries | 76 |
| Agent tools | 37 |
| Tool definitions | 37 |
| Legacy registry entries | 26 |
| Legacy registry entries without v2 alias coverage | 0 |
| Capability records | 38 |
| Capability tool records | 37 |
| Capability workflow records | 1 |
| Unapproved direct Agent default bypass count | 0 |
| Unauthorized write path count | 0 |
| UI direct business write count | 0 |
| Specialist direct business call count | 0 |
| Pipeline Agent bypass count | 0 |

## V2 ToolDefinition Coverage

| Tool | Aliases | Operation type |
| --- | --- | --- |
| `approval.confirm_plan` | `strategy_confirmation_execute` | write |
| `backfill.commit` | `backfill_execute` | write |
| `backfill.preview` | `backfill_preview` | proposal |
| `capital.change.commit` | `capital_management_execute` | write |
| `capital.change.preview` | `capital_management_preview` | proposal |
| `evidence.get_market_evidence` |  | read |
| `evidence.get_stock_evidence` |  | read |
| `evidence.mcp_readonly_evidence` | `mcp_market_risk_summary` | read |
| `evidence.search_news` | `stock_news`, `news_search` | read |
| `evidence.search_rag` | `stock_rag`, `rag_search` | read |
| `market.analyze_stock` | `stock_analysis` | read |
| `market.compare_stocks` |  | read |
| `market.get_ranking` | `ranking` | read |
| `market.get_signal_summary` | `classic_ranking` | read |
| `market.lookup_stock` | `stock_lookup`, `classic_stock_score` | read |
| `mcp.readonly.invoke` | `mcp_tool` | read |
| `portfolio.analyze_risk` | `portfolio_risk` | read |
| `portfolio.commit_paper_trade` | `paper_trade_execute`, `paper_trading_execution_tool` | write |
| `portfolio.compare_risk_before_after` | `portfolio_risk_compare` | read |
| `portfolio.get_account_summary` | `portfolio_account_summary` | read |
| `portfolio.get_orders` | `portfolio_orders` | read |
| `portfolio.get_positions` | `portfolio_positions` | read |
| `portfolio.get_state` | `portfolio_state` | read |
| `portfolio.preview_adjust_position` | `adjust_position` | proposal |
| `portfolio.preview_manual_change` | `manual_position_operation_tool` | proposal |
| `portfolio.preview_paper_trade` | `paper_trade_preview` | proposal |
| `portfolio.preview_rebalance` | `rebalance_plan` | proposal |
| `portfolio.recommend_position` | `position_recommendation` | read |
| `portfolio.recommend_replacement` | `replacement_recommendation` | read |
| `report.list_latest` | `report`, `report_latest` | read |
| `sandbox.python_analysis` | `python_sandbox_analysis` | system |
| `strategy.builder.preview` | `strategy_builder_tool` | proposal |
| `strategy.disable.commit` | `strategy_disable_commit` | write |
| `strategy.disable.preview` | `strategy_disable_preview` | proposal |
| `strategy.management.preview` | `strategy_management_tool` | proposal |
| `system.scheduler_status` | `scheduler_status` | system |
| `user.profile.get` | `user_profile` | read |

## Services and Adapters

Directly reusable service layer:

- `agent/services/market_analysis_service.py`: `MarketAnalysisService`, `RankingRepository`, `StockMetadataRepository`, `PredictionRepository`, `ScoreRepository`.
- `agent/services/evidence_service.py`: `EvidenceService`, `NewsRepository`, `RagRepository`, `McpEvidenceClient`, `SourceFormatter`.
- `agent/services/portfolio_service.py`: `PortfolioService`, `AccountRepository`, `PortfolioRepository`, `OrderRepository`.
- `agent/services/portfolio_risk_service.py`: `PortfolioRiskService`, `RiskRepository`.
- `agent/services/portfolio_proposal_service.py`: proposal-only portfolio operation service.
- `agent/services/write_operation_service.py`: write preview/commit service, still behind approval and revalidation.

Adapter layer now covers market, evidence, portfolio state, portfolio risk, portfolio proposals, system auxiliary tools, MCP read-only evidence, and strategy/capital/backfill write previews and commits.

## Legacy Compatibility Wrappers

The following legacy entry points remain intentionally available as compatibility wrappers, with planned-removal comments:

- `agent/tools/ranking_tool.py::query_ranking`
- `agent/tools/stock_lookup_tool.py::lookup_stock`
- `agent/tools/stock_analysis_tool.py::analyze_stock`
- `agent/tools/stock_news_tool.py::query_stock_news`
- `agent/tools/stock_rag_tool.py::query_stock_rag`
- `agent/tools/portfolio_state_tool.py::query_portfolio_state`
- `agent/tools/portfolio_risk_tool.py::query_portfolio_risk`

Agent default execution now goes through `agent/tool_engine.py` ToolDefinitions and ToolExecutor aliases. Remaining direct calls are whitelisted compatibility, UI confirmation, or internal gateway/service calls.

## CapabilityIndex and Artifact Result

- `agent/capability_index.py::build_trusted_capability_index` now builds from v2 ToolDefinitions and workflow records, not from the legacy registry fallback.
- Representative v2 tools were checked for artifact creation through ToolExecutor.
- Write tools remain marked as approval-required and are not exposed through MCP write paths.
- MCP write-like tool names remain blocked or absent from the exposed read-only MCP path.

Representative artifact-tested tools:

- `ranking`
- `stock_analysis`
- `stock_news`
- `portfolio_state`
- `portfolio.analyze_risk`
- `portfolio.preview_rebalance`

## Test Results

Passed:

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts`
- `py -3 -m pytest tests/unit/test_phase11_final_tool_coverage.py -q` -> 6 passed
- `py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q` -> 7 passed
- `py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q` -> 6 passed
- `py -3 -m pytest tests/unit/test_agent_write_requires_confirmation.py -q` -> 1 passed
- `py -3 -m pytest tests/unit/test_agent_action_proposal_gateway.py -q` -> 3 passed
- `py -3 -m pytest tests/unit/test_multi_agent_phase3_human_approval.py -q` -> 5 passed
- `py -3 -m pytest tests/unit/test_phase10_goal_planning.py -q` -> 13 passed
- `py -3 -m pytest tests/unit/test_phase10_3_capability_artifacts.py -q` -> 9 passed
- `py -3 -m pytest tests/unit/test_mcp_phase9_financial_evidence.py -q` -> 17 passed
- `py -3 -m pytest tests/unit/test_phase11_p1b_system_aux_tools.py -q` -> 8 passed
- `py -3 -m pytest tests/unit/test_phase11_p2a_market_analysis_service.py -q` -> 6 passed
- `py -3 -m pytest tests/unit/test_phase11_p2b_evidence_service.py -q` -> 6 passed
- `py -3 -m pytest tests/unit/test_phase11_p2c_portfolio_risk_services.py -q` -> 5 passed
- `py -3 -m pytest tests/unit/test_phase11_p1a_portfolio_proposal_tools.py -q` -> 6 passed
- `py -3 -m pytest tests/unit/test_ai_paper_trading_page.py tests/unit/test_agent_portfolio_tool.py -q` -> 9 passed
- `py -3 -m pytest tests/unit/test_agent_position_and_strategy_intents.py -q` -> 4 passed
- `py -3 -m pytest tests/unit/test_agent_runtime_contracts.py -q` -> 4 passed

Known non-blocking warnings:

- Existing `datetime.utcnow()` deprecation warnings in several older tests.

## 8501 UI Acceptance

Health:

- `http://127.0.0.1:8501/_stcore/health` -> `200`, `ok`.

Browser-opened page checks:

| Page | Checked content | Result |
| --- | --- | --- |
| Home / prediction ranking | App title, disclaimer, model library, manual ranking generation, daily update generation | Passed |
| AI Agent | Agent control center, conversation input, clear conversation, quick question examples | Passed |
| AI paper trading | Page title, update entry, account summary, positions, risk sections | Passed |
| System monitor | System monitor title, overall status, save snapshot, Runtime Reliability | Passed |

No visible traceback, `ModuleNotFoundError`, `NameError`, unhandled script exception, or mojibake was detected in the checked pages. Destructive/write UI actions were not clicked.

## Remaining Risk

- Legacy wrappers still exist by design for page, pipeline, and test compatibility.
- Some older project documents or historical console outputs may still contain encoding artifacts, but checked Streamlit pages did not show mojibake.
- Full end-to-end write execution was not performed from the UI because it would mutate business data; approval and write gateway paths were covered by unit tests.

NEXT_STAGE_ALLOWED = true
