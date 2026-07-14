# Phase 11.1-C P1-A Portfolio Proposal Tool Migration Report

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## 1. 修改前状态表

| tool | legacy file | legacy caller | current execution path before migration | direct branch location | read/proposal/write | requires_approval | current result type | through ToolExecutor before | planned canonical tool | planned adapter | planned service |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `position_recommendation` | `agent/tools/position_recommendation_tool.py` | `agent/executor.py`, `agent/orchestration/multi_task_executor.py` | legacy function direct call | `agent/executor.py` position branch; `multi_task_executor.py` fallback | read | false | `ToolResult` / dict | false | `portfolio.recommend_position` | `portfolio_recommend_position_adapter` | `PortfolioProposalService.recommend_position` |
| `replacement_recommendation` | `agent/tools/replacement_recommendation_tool.py` | `agent/executor.py`, `agent/orchestration/multi_task_executor.py` | legacy function direct call | `agent/executor.py` replacement branch; `multi_task_executor.py` fallback | read | false | `ToolResult` / dict | false | `portfolio.recommend_replacement` | `portfolio_recommend_replacement_adapter` | `PortfolioProposalService.recommend_replacement` |
| `manual_position_operation_tool` | `agent/tools/manual_position_operation_tool.py` | `agent/specialists/risk_operation.py`, legacy registry | specialist direct call | `RiskOperationAgent.run()` | proposal | confirmation plan required when executable | `ToolResult` | false | `portfolio.preview_manual_change` | `portfolio_preview_manual_change_adapter` | `PortfolioProposalService.preview_manual_position_change` |
| `rebalance_plan` | `agent/tools/rebalance_plan_tool.py` | legacy registry, add-stock preview path | legacy preview direct call | `agent/executor.py` preview branch | proposal | confirmation plan required | `ToolResult` | false | `portfolio.preview_rebalance` | `portfolio_preview_rebalance_adapter` | `PortfolioProposalService.preview_rebalance` |
| `adjust_position` | `agent/tools/rebalance_plan_tool.py` | `agent/executor.py`, legacy registry | legacy preview direct call | `agent/executor.py` adjust branch | proposal | confirmation plan required | `ToolResult` | false | `portfolio.preview_adjust_position` | `portfolio_preview_adjust_position_adapter` | `PortfolioProposalService.preview_adjust_position` |
| `paper_trade_preview` | `agent/tools/paper_trade_preview_tool.py` | legacy registry | legacy wrapper to add-stock preview | registry-only / indirect | proposal | confirmation plan required | `ToolResult` | false | `portfolio.preview_paper_trade` | `portfolio_preview_paper_trade_adapter` | `PortfolioProposalService.preview_paper_trade` |
| `paper_trade_execute` | `agent/tools/paper_trade_execute_tool.py` | `confirm_execute`, P0 confirmation service | legacy commit function | `agent/executor.py` confirm branch; `WriteOperationService.confirm_existing_plan()` | write | true | `ToolResult` | false | `portfolio.commit_paper_trade` | `portfolio_commit_paper_trade_adapter` | `PortfolioProposalService.commit_paper_trade` |
| `paper_trading_execution_tool` | `agent/tools/paper_trade_execute_tool.py` | legacy registry alias | same legacy commit function | legacy registry | write | true | `ToolResult` | false | `portfolio.commit_paper_trade` | `portfolio_commit_paper_trade_adapter` | `PortfolioProposalService.commit_paper_trade` |

## 2. 迁移结果

| legacy_name | canonical_name | old_file | old_callers | new_adapter | domain_service | operation_type | tool_definition_status | adapter_status | tool_executor_status | unified_result_status | artifact_status | legacy_wrapper_status | legacy_disabled_for_agent | remaining_non_agent_callers | tests | status | remaining_issue |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `position_recommendation` | `portfolio.recommend_position` | `agent/tools/position_recommendation_tool.py` | old executor, old multi fallback | `portfolio_recommend_position_adapter` | `PortfolioProposalService.recommend_position` | read | registered | created | default path | yes | saved through `ToolExecutor` | retained as business implementation | true | direct legacy unit tests | `test_position_recommendation_alias_matches_legacy_core_fields` | default_v2 | none |
| `replacement_recommendation` | `portfolio.recommend_replacement` | `agent/tools/replacement_recommendation_tool.py` | old executor, old multi fallback | `portfolio_recommend_replacement_adapter` | `PortfolioProposalService.recommend_replacement` | read | registered | created | default path | yes | saved through `ToolExecutor` | retained as business implementation | true | direct legacy unit tests | registry and capability tests | default_v2 | none |
| `manual_position_operation_tool` | `portfolio.preview_manual_change` | `agent/tools/manual_position_operation_tool.py` | `RiskOperationAgent` | `portfolio_preview_manual_change_adapter` | `PortfolioProposalService.preview_manual_position_change` | proposal | registered | created | default path | yes | saved through `ToolExecutor` | retained as business implementation | true | direct legacy tests and old registry | `test_phase11_p1a_tools_are_registered_with_legacy_aliases` | default_v2 | none |
| `rebalance_plan` | `portfolio.preview_rebalance` | `agent/tools/rebalance_plan_tool.py` | old preview branch, old registry | `portfolio_preview_rebalance_adapter` | `PortfolioProposalService.preview_rebalance` | proposal | registered | created | default path | yes | saved through `ToolExecutor` | retained as business implementation | true | direct legacy rebalance tests | `test_rebalance_preview_alias_keeps_preview_only_behavior` | default_v2 | none |
| `adjust_position` | `portfolio.preview_adjust_position` | `agent/tools/rebalance_plan_tool.py` | old adjust branch, old registry | `portfolio_preview_adjust_position_adapter` | `PortfolioProposalService.preview_adjust_position` | proposal | registered | created | default path | yes | saved through `ToolExecutor` | retained as business implementation | true | direct legacy rebalance tests | paper trade regression tests | default_v2 | none |
| `paper_trade_preview` | `portfolio.preview_paper_trade` | `agent/tools/paper_trade_preview_tool.py` | old registry | `portfolio_preview_paper_trade_adapter` | `PortfolioProposalService.preview_paper_trade` | proposal | registered | created | default path | yes | saved through `ToolExecutor` | retained as compatibility wrapper | true | old registry | gateway tests | default_v2 | none |
| `paper_trade_execute` | `portfolio.commit_paper_trade` | `agent/tools/paper_trade_execute_tool.py` | old confirm branch, P0 confirm service | `portfolio_commit_paper_trade_adapter` | `PortfolioProposalService.commit_paper_trade` | write | registered | created | Write Gateway selected path | yes | saved through `ToolExecutor` | retained as commit implementation | true | direct legacy execution tests | `test_commit_requires_approval_and_gateway_selects_portfolio_commit` | default_v2 | none |
| `paper_trading_execution_tool` | `portfolio.commit_paper_trade` | `agent/tools/paper_trade_execute_tool.py` | old registry alias | `portfolio_commit_paper_trade_adapter` | `PortfolioProposalService.commit_paper_trade` | write | registered alias | created | Write Gateway selected path | yes | saved through `ToolExecutor` | retained as alias compatibility | true | old registry contract tests | registry tests | default_v2 | none |

## 3. Gateway and Safety

- `agent/write_gateway.py` now maps `execute_add_stock` and `execute_adjust_position` to `portfolio.commit_paper_trade`.
- `agent/services/write_operation_service.py` no longer imports `paper_trade_execute_tool` directly for paper-trading plans; the compatibility confirmation path delegates to `PortfolioProposalService.commit_paper_trade`.
- `portfolio.commit_paper_trade` is `OP_WRITE`, `requires_approval=True`, and fails with `approval_required` when called without approval.
- The old token, plan hash, business-state revalidation, trading-day validation and idempotency logic remains in `agent/tools/paper_trade_execute_tool.py` and is reused unchanged by the service.

## 4. Agent Mainline Legacy Disablement

- `agent/executor.py` keeps intent routing branches, but the migrated branches call v2 tools through `_registered_tool()` or `execute_confirmed_plan_v2()`.
- `agent/orchestration/multi_task_executor.py` sends registered read/proposal tools to v2 `ToolExecutor` and no longer has legacy fallback branches for `position_recommendation` or `replacement_recommendation`.
- `agent/specialists/risk_operation.py` no longer directly calls `preview_manual_position_operation()`; it executes `portfolio.preview_manual_change` through `ToolExecutor`.
- Static check found no direct calls to this batch's legacy business functions in `agent/executor.py`, `agent/orchestration/multi_task_executor.py`, `agent/specialists/risk_operation.py`, `agent/write_gateway.py`, or `agent/services/write_operation_service.py`.

## 5. Business Rule Preservation

- One-lot validation, cash allocation, recursive allocation and order preview logic were not rewritten.
- `portfolio/target_weight_allocator.py`, `portfolio/rebalance_rules.py`, `portfolio/paper_trading_engine.py`, `pipelines/paper_trading_pipeline.py`, and `scoring/final_score.py` were not modified.
- Existing legacy tool unit tests continue to call the original functions directly for behavior compatibility.

## 6. Capability Index and Artifact Coverage

- Capability Index records now point legacy names to v2 canonical tools:
  - `position_recommendation -> portfolio.recommend_position`
  - `replacement_recommendation -> portfolio.recommend_replacement`
  - `manual_position_operation_tool -> portfolio.preview_manual_change`
  - `rebalance_plan -> portfolio.preview_rebalance`
  - `adjust_position -> portfolio.preview_adjust_position`
  - `paper_trade_preview -> portfolio.preview_paper_trade`
  - `paper_trade_execute / paper_trading_execution_tool -> portfolio.commit_paper_trade`
- `OP_PROPOSAL` is exposed as `permission_scope=preview` in the capability index.
- `agent/artifacts.py` now stores empty `run_id` as `NULL`, fixing artifact persistence when a v2 tool runs outside an existing runtime run.

## 7. Tests

Passed:

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests\unit\test_phase11_p1a_portfolio_proposal_tools.py -q
py -3 -m pytest tests\unit\test_phase11_intent_tool_engine.py -q
py -3 -m pytest tests\unit\test_phase11_p0_write_gateway.py -q
py -3 -m pytest tests\unit\test_agent_write_requires_confirmation.py tests\unit\test_agent_action_proposal_gateway.py -q
py -3 -m pytest tests\unit\test_multi_agent_phase3_human_approval.py -q
py -3 -m pytest tests\unit\test_phase10_goal_planning.py -q
py -3 -m pytest tests\unit\test_phase10_3_capability_artifacts.py -q
py -3 -m pytest tests\unit\test_agent_paper_trade_execution.py tests\unit\test_agent_rebalance_preview.py tests\unit\test_agent_position_recommendation.py tests\unit\test_agent_replacement_recommendation.py -q
py -3 -m pytest tests\unit\test_agent_position_and_strategy_intents.py tests\unit\test_agent_runtime_contracts.py -q
```

Note: `tests/unit/test_agent_paper_trade_execution.py` now fixes the test-only preview date to `2026-06-12` to avoid real-calendar weekend failures. Production non-trading-day validation is unchanged.

## 8. Not Migrated in This Batch

- News / RAG tools.
- Full ranking / stock analysis refactor.
- Full `PortfolioService` or `PortfolioRiskService` extraction.
- MCP read-only tools.
- `python_sandbox_analysis`.
- Strategy builder / strategy registration write path beyond the existing P0 confirmation adapter.
