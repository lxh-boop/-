# Phase 11.1-B P0 Write Tool Migration Report

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

审计基线：`docs/phase11_1_tool_refactor_inventory_report.md`  
本批目标：只关闭 4 个 P0 写操作绕过，不迁移 P1/P2/P3 工具，不重写模拟盘、回填、RAG、排名或风险业务逻辑。

## 1. 状态总览

| P0 ID | old_entry | old_direct_write | new_tool_definition | new_adapter | new_service | new_gateway | old_entry_status | legacy_disabled | tests | remaining_issue |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P0-1 strategy disable | `agent/tools/strategy_management_tool.py:manage_strategy(action="disable")` | `registry.disable()` | `strategy.disable.preview`, `strategy.disable.commit` | `strategy_disable_preview_adapter`, `strategy_disable_commit_adapter` | `WriteOperationService.create_strategy_disable_proposal`, `commit_strategy_disable` | `execute_confirmed_plan_v2` | `legacy_disabled` | true | `test_strategy_disable_generates_proposal_then_gateway_commits`, `test_strategy_disable_revalidates_state_change` | 原不可达旧分支保留禁用占位，后续可清理 |
| P0-2 AI paper backfill page | `app/pages/ai_paper_trading.py` backfill button | `run_ai_paper_backfill()` | `backfill.preview`, `backfill.commit` | `backfill_preview_adapter`, `backfill_commit_adapter` | `WriteOperationService.create_backfill_proposal`, `commit_backfill` | `execute_confirmed_plan_v2` | `legacy_disabled` | true | `test_backfill_preview_does_not_execute_until_gateway_confirm` | 页面会先生成 plan；确认后执行 |
| P0-3 AI paper capital page | `app/pages/ai_paper_trading.py` capital button | `add_paper_cash_flow()` | `capital.change.preview`, `capital.change.commit` | `capital_change_preview_adapter`, `capital_change_commit_adapter` | `WriteOperationService.create_capital_change_proposal`, `commit_capital_change` | `execute_confirmed_plan_v2` | `legacy_disabled` | true | `test_capital_change_uses_gateway_and_is_idempotent` | 页面会先生成 plan；确认后写入 pending cash flow |
| P0-4 AI Agent confirm button | `app/pages/ai_agent.py:_render_pending_plan()` | `execute_confirmed_*()` | `approval.confirm_plan`, plus specific commit tools | `approval_confirm_plan_adapter` | `WriteOperationService.confirm_existing_plan` | `execute_confirmed_plan_v2` | `legacy_disabled` | true | `test_write_gateway_rejects_missing_and_unknown_plan`, existing Phase 3 approval tests | 页面只提交 `plan_id`/`confirmation_token` 给 Gateway |

状态枚举：`legacy_disabled`。

## 2. 新增/修改文件

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `agent/services/__init__.py` | 新增 | service layer package |
| `agent/services/write_operation_service.py` | 新增 | P0 写操作 proposal/revalidate/commit service |
| `agent/tools/write_operation_adapters.py` | 新增 | P0 v2 ToolAdapter |
| `agent/write_gateway.py` | 新增 | 统一确认入口，按 pending plan intent 路由到 v2 write tool |
| `agent/tool_engine.py` | 修改 | 注册 7 个 P0 v2 工具 |
| `agent/tools/strategy_management_tool.py` | 修改 | `disable` 不再直接写 registry，改为 proposal |
| `agent/tools/capital_management_tool.py` | 修改 | 旧函数名保留，但委托 service |
| `agent/tools/backfill_tool.py` | 修改 | 旧函数名保留，但委托 service |
| `app/pages/ai_agent.py` | 修改 | 确认按钮改走 Write Gateway |
| `app/pages/ai_paper_trading.py` | 修改 | 回填/资金按钮改为先生成 proposal，确认后 Gateway commit |
| `tests/unit/test_phase11_p0_write_gateway.py` | 新增 | P0 闭环测试 |
| `tests/unit/test_multi_agent_phase3_human_approval.py` | 修改 | 测试固定交易日，避免真实日期导致周末失败 |

## 3. 新链路

### P0-1 Strategy Disable

```text
manage_strategy(action="disable")
-> WriteOperationService.create_strategy_disable_proposal()
-> confirmation plan: disable_strategy
-> execute_confirmed_plan_v2()
-> ToolExecutor(strategy.disable.commit)
-> WriteOperationService.commit_strategy_disable()
-> validate token / plan_hash / expiry
-> revalidate current strategy state
-> registry.disable()
-> mark_plan_executed + audit
```

### P0-2 Backfill

```text
AI paper page button
-> ToolExecutor(backfill.preview)
-> WriteOperationService.create_backfill_proposal()
-> user confirmation
-> execute_confirmed_plan_v2()
-> ToolExecutor(backfill.commit)
-> validate token / plan_hash / expiry
-> revalidate current account snapshot
-> run_paper_trading_backfill()
-> mark_plan_executed + audit
```

### P0-3 Capital Change

```text
AI paper page capital submit
-> ToolExecutor(capital.change.preview)
-> WriteOperationService.create_capital_change_proposal()
-> user confirmation
-> execute_confirmed_plan_v2()
-> ToolExecutor(capital.change.commit)
-> validate token / plan_hash / expiry
-> revalidate current cash snapshot
-> add_cash_flow()
-> mark_plan_executed + audit
```

### P0-4 Agent Confirm Button

```text
AI Agent pending plan confirm button
-> execute_confirmed_plan_v2(plan_id, token, user_id, ...)
-> load pending plan
-> select v2 write tool by intent
-> ToolExecutor(..., approval_granted=True)
-> legacy-safe service commit path
-> UnifiedToolResult + artifact when context is available
```

Supported plan intents:

- `execute_add_stock`
- `execute_adjust_position`
- `capital_change`
- `paper_backfill`
- `disable_strategy`
- `register_strategy`
- `enable_strategy`

## 4. 行为一致性

| 场景 | 旧行为 | 新行为 | 权限是否放松 | 副作用 |
| --- | --- | --- | --- | --- |
| 策略禁用 | 直接写 registry | 先 proposal，确认后禁用 | 否，更严格 | 未确认不写 |
| 回填页面 | 点击即执行回填 | 点击生成 proposal，确认后回填 | 否，更严格 | 未确认不回填 |
| 资金页面 | 点击即新增 cash flow | 点击生成 proposal，确认后新增 | 否，更严格 | 未确认不写资金流水 |
| Agent 确认按钮 | 直接调用 commit 函数 | Gateway -> ToolExecutor -> service | 否，更统一 | 仍保留原 token/plan_hash/revalidate |

## 5. 测试结果记录

已通过：

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests\unit\test_phase11_intent_tool_engine.py -q
py -3 -m pytest tests\unit\test_agent_write_requires_confirmation.py -q
py -3 -m pytest tests\unit\test_agent_action_proposal_gateway.py -q
py -3 -m pytest tests\unit\test_multi_agent_phase3_human_approval.py -q
py -3 -m pytest tests\unit\test_phase10_goal_planning.py -q
py -3 -m pytest tests\unit\test_phase10_3_capability_artifacts.py -q
py -3 -m pytest tests\unit\test_phase11_p0_write_gateway.py -q
py -3 -m pytest tests\unit\test_phase11_p0_write_gateway.py tests\unit\test_multi_agent_phase3_human_approval.py -q
py -3 -m pytest tests\unit\test_phase11_p0_write_gateway.py tests\unit\test_phase11_intent_tool_engine.py tests\unit\test_agent_capital_management_tool.py tests\unit\test_agent_action_proposal_gateway.py tests\unit\test_multi_agent_phase3_human_approval.py -q
```

测试日期稳定性：

- `tests/unit/test_multi_agent_phase3_human_approval.py` 通过 autouse fixture 固定调仓预览日期为 `2026-06-12`。
- 未放松生产交易日校验。
- 非交易日仍由 `agent/tools/paper_trade_execute_tool.py` 的原规则拒绝。

## 6. 页面与 8501 验证

8501 部署：

```text
http://127.0.0.1:8501/_stcore/health -> ok
```

页面检查：

| 页面 | 结果 | 备注 |
| --- | --- | --- |
| 首页 / 预测排名 | 通过 | 页面可打开，免责声明可见，无 `Traceback`/`ModuleNotFoundError`/`NameError` |
| AI Agent | 通过 | 页面可打开，Agent 控制中心和待确认区域可见，无应用错误 |
| AI 模拟盘 | 通过 | 页面可打开，历史回放和资金管理入口可见，无应用错误 |

## 7. 未处理 P1/P2 清单

本批明确未迁移：

- `position_recommendation`
- `replacement_recommendation`
- `manual_position_operation_tool`
- `rebalance_plan`
- `adjust_position`
- `stock_lookup`
- `user_profile`
- `python_sandbox_analysis`
- MCP read-only tools
- 新闻/RAG 重构
- ranking/stock_analysis 重构
- PortfolioService / PortfolioRiskService 全量重构
