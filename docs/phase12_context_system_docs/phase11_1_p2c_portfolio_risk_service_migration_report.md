# Phase 11.1 / P2-C PortfolioService and PortfolioRiskService Migration Report

## Scope

This stage centralized read-only paper-account, position, order and risk
analysis access behind service classes. It did not change the paper-trading
engine, order commit path, revalidation, idempotency, allocation rules or P1-A
proposal algorithms.

## Pre-change Status

| Area | Before | Risk | Stage action |
| --- | --- | --- | --- |
| Portfolio state | `agent/tools/portfolio_state_tool.py::query_portfolio_state` read `PortfolioStorage` directly. | Agent default path could bypass a unified service contract. | Kept the function as a compatibility wrapper and routed it through `PortfolioService.get_portfolio_state()`. |
| Portfolio risk | `agent/tools/portfolio_risk_tool.py::query_portfolio_risk` loaded storage and called `calculate_portfolio_risk()` directly. | Risk output shape and source metadata were not unified. | Kept the function as a compatibility wrapper and routed it through `PortfolioRiskService.analyze_current_risk()`. |
| ToolExecutor | `portfolio.get_state` and `portfolio.analyze_risk` existed but their handlers called old wrappers directly. | The v2 name existed, but service ownership was unclear. | Handlers now call service adapters. |
| Multi-task executor | Had direct fallback branches for `portfolio_state` and `portfolio_risk`. | Agent could bypass v2 ToolExecutor if registry resolution failed. | Removed the direct fallback execution. |
| Additional read surfaces | Account, positions, orders and risk comparison were not separately exposed as v2 tools. | Specialist agents had to over-fetch full state. | Added read-only v2 tools for account summary, positions, orders and risk comparison. |

## Implemented Changes

- Added `agent/services/portfolio_service.py`.
  - Classes: `AccountRepository`, `PortfolioRepository`, `OrderRepository`, `PortfolioService`.
  - Methods: `get_account_summary`, `get_current_positions`, `get_current_orders`,
    `get_portfolio_state`, `get_cash_state`, `get_position_weights`,
    `get_historical_account_snapshot`.
- Added `agent/services/portfolio_risk_service.py`.
  - Classes: `RiskRepository`, `PortfolioRiskService`.
  - Methods: `analyze_current_risk`, `calculate_concentration`,
    `calculate_single_stock_weight`, `calculate_industry_exposure`,
    `calculate_drawdown`, `compare_risk_before_after`, `build_risk_summary`.
- Added adapters:
  - `agent/tools/portfolio_state_adapters.py`
  - `agent/tools/portfolio_risk_adapters.py`
- Updated wrappers:
  - `agent/tools/portfolio_state_tool.py`
  - `agent/tools/portfolio_risk_tool.py`
- Updated `agent/tool_engine.py` registrations:
  - `portfolio.get_state` with legacy alias `portfolio_state`
  - `portfolio.get_account_summary` with legacy alias `portfolio_account_summary`
  - `portfolio.get_positions` with legacy alias `portfolio_positions`
  - `portfolio.get_orders` with legacy alias `portfolio_orders`
  - `portfolio.analyze_risk` with legacy alias `portfolio_risk`
  - `portfolio.compare_risk_before_after` with legacy alias `portfolio_risk_compare`
- Updated `agent/orchestration/multi_task_executor.py`.
  - Removed direct portfolio fallback execution.
  - Added filter/read-intent support for the new canonical portfolio tools.
- Updated `agent/capability_index.py` output/action mappings for canonical portfolio tools.
- Removed unused direct portfolio imports from `agent/executor.py`.
- Added `tests/unit/test_phase11_p2c_portfolio_risk_services.py`.

## Unified Result Contract

Portfolio read tools now consistently include relevant fields such as:

- `account`
- `account_summary`
- `positions`
- `orders`
- `risk`
- `risk_report`
- `summary`
- `as_of_date`
- `sources`
- `not_executed: true`
- `mutation_performed: false`

## Tests

Required tests:

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts` -> passed
- `py -3 -m pytest tests/unit/test_phase11_p2c_portfolio_risk_services.py -q` -> 5 passed
- `py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q` -> 7 passed
- `py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q` -> 6 passed
- `py -3 -m pytest tests/unit/test_phase10_goal_planning.py -q` -> 13 passed
- `py -3 -m pytest tests/unit/test_phase10_3_capability_artifacts.py -q` -> 9 passed

Additional compatibility tests:

- `py -3 -m pytest tests/unit/test_phase11_p1a_portfolio_proposal_tools.py -q` -> 6 passed
- `py -3 -m pytest tests/unit/test_ai_paper_trading_page.py tests/unit/test_agent_portfolio_tool.py -q` -> 9 passed

Known warnings:

- Existing `datetime.utcnow()` deprecation warnings in capability-index tests.
  They were not introduced by this stage and did not fail the run.

## Risk Notes

- P1-A proposal tools still use the existing legacy algorithms internally, but
  their portfolio reads now go through the compatibility wrappers backed by the
  new services.
- Paper-trading writers, order commit, approval, revalidate, rollback-related
  metadata and idempotency were not changed.
- `PortfolioService` and `PortfolioRiskService` are read-only. They do not
  commit orders, mutate user profile, run RAG/news retrieval, or call Streamlit UI.

NEXT_STAGE_ALLOWED = true
