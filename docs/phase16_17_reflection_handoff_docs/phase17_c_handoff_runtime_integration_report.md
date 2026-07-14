# Phase 17-C Coordinator / Specialist Handoff 运行时接入报告

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## 阶段范围

- 阶段：Phase 17-C / 阶段G。
- 本阶段将 Phase17 Handoff 协议最小侵入接入现有 multi-agent runtime。
- 旧接口 `agent_outputs`、`agent_timeline`、`multi_agent`、`protected_operation` 保持兼容。
- Specialist 仍不能直接写模拟盘、策略或资金状态。
- 写操作仍必须经过 WriteGateway / approval / revalidate / commit。

## 新增/修改文件

新增：

- `agent/handoff/handoff_coordinator.py`
- `agent/handoff/specialist_adapter.py`
- `app/handoff_ui.py`
- `tests/unit/test_phase17_handoff_coordinator.py`
- `tests/unit/test_phase17_handoff_executor_integration.py`
- `tests/unit/test_phase17_handoff_ui_safe_summary.py`

修改：

- `agent/handoff/__init__.py`
- `agent/executor.py`
- `agent/communication/message_types.py`
- `agent/communication/message_router.py`
- `agent/context/context_types.py`
- `agent/context/context_policy.py`
- `app/pages/ai_agent.py`
- `app/pages/system_monitor.py`

## Coordinator 能力

实现位置：`agent/handoff/handoff_coordinator.py::HandoffCoordinator`

已实现：

- `plan_handoff()`
- `execute_handoff()`
- `merge_handoff_results()`
- `stop_on_blocking_result()`
- `limit_handoff_depth()`

运行限制：

- `max_handoff_depth` 默认 2。
- `max_specialists_per_run` 默认 3。
- `same_role_repeat` 默认 1。
- 每次 handoff 发布安全消息，不发布 raw payload。
- 阻断时不调用 runner。

消息发布：

- `HANDOFF_REQUESTED`
- `HANDOFF_ACCEPTED`
- `HANDOFF_RESULT`
- `HANDOFF_BLOCKED`

## SpecialistAdapter 能力

实现位置：`agent/handoff/specialist_adapter.py::SpecialistAdapter`

已实现：

- `run_portfolio_analyst()`
- `run_risk_analyst()`
- `run_evidence_retriever()`
- `run_strategy_guard()`
- `run_report_writer()`
- `run_system_diagnostic()`
- `result_from_agent_output()`

边界：

- Adapter 不直接 commit。
- Adapter 不直接改持仓、策略或资金。
- Adapter 只把现有 specialist 的 `AgentOutput` 转为 `HandoffResult`。
- 输出仅包含 summary、findings、refs、warnings、errors、metadata 摘要。

## Executor 接入点

实现位置：

- `agent/executor.py::_execute_readonly_multi_agent_collaboration`
- `agent/executor.py::_execute_position_approval_multi_agent_workflow`

接入方式：

- 保留旧 specialist 调用：`MarketIntelligenceAgent`、`PortfolioAnalysisAgent`、`RiskOperationAgent`、`ReportingAgent`。
- 在每个 specialist 调用外层创建 `HandoffRequest`。
- 通过 `HandoffCoordinator.execute_handoff()` 包裹调用。
- specialist 完成后由 `SpecialistAdapter.result_from_agent_output()` 生成 `HandoffResult`。
- `orchestration["phase17_handoff"]` 保存安全 handoff summary。
- `context_payload["phase17_handoff"]` 只保存 refs 和 summary。

只读 multi-agent 路径实际 roles：

- `EVIDENCE_RETRIEVER`
- `PORTFOLIO_ANALYST`
- `REPORT_WRITER`

保护性调仓 preview 路径实际 roles：

- `EVIDENCE_RETRIEVER`
- `PORTFOLIO_ANALYST`
- `STRATEGY_GUARD`

## Context 接入点

实现位置：

- `agent/context/context_types.py::RuntimeContext`
- `agent/context/context_policy.py::LLM_VISIBLE_KEYS`

新增安全字段：

- `handoff_refs`
- `latest_handoff_trace_id`
- `handoff_role_summaries`

约束：

- Context 只携带 refs 和摘要。
- 不携带 `confirmation_token`、API key、数据库路径、本地路径、stack trace、raw payload、raw positions、raw evidence。

## MessageBus 接入点

实现位置：

- `agent/communication/message_types.py::MessageType`
- `agent/communication/message_router.py::MessageRouter`

新增消息类型：

- `HANDOFF_ACCEPTED`
- `HANDOFF_RESULT`
- `HANDOFF_BLOCKED`

`HANDOFF_REQUESTED` 继续复用已有枚举。

路由：

- Handoff 消息路由到 `ui` 和 `audit`。
- 可见性为 `UI_VISIBLE`。
- Payload 只包含 handoff id、source/target role、status、summary、refs count、blocked reason。

## UI 接入点

AI Agent：

- 文件：`app/pages/ai_agent.py`
- Helper：`app/handoff_ui.py`
- 展示：
  - caption：`Handoff: count=... | roles=... | latest=... | blocked=...`
  - 折叠区：`Handoff 安全摘要`
  - 懒加载 checkbox：`Load Handoff safe summary`

系统监控：

- 文件：`app/pages/system_monitor.py`
- 新增区块：`Handoff Health`
- 指标：
  - latest handoff count
  - latest handoff status
  - blocked handoff count
  - roles used
  - handoff messages seen
  - secret safe

## WriteGateway 边界说明

- `STRATEGY_GUARD` 只允许 proposal preview 工具，例如 `portfolio.preview_manual_change`。
- `approval.confirm_plan`、`paper_trade_execute`、`strategy_confirmation_execute`、`capital_management_execute`、`backfill_execute` 不会进入 specialist allowed tools。
- 调仓 preview 产生 `waiting_for_approval`，不会写持仓。
- Confirm 后仍走现有 `agent/write_gateway.py::execute_confirmed_plan_v2`。
- 本阶段未修改 commit、approval、revalidate、idempotency 逻辑。

## 兼容旧接口

保持不变：

- `orchestration["multi_agent"]`
- `orchestration["agent_outputs"]`
- `orchestration["agent_timeline"]`
- `orchestration["tool_calls"]`
- `runtime` / `context` / `reflection`
- 旧 `handoff_from` / `handoff_to` metadata

新增：

- `orchestration["phase17_handoff"]`
- `context["phase17_handoff"]`
- MessageBus `HANDOFF_*` messages

## 测试结果

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts`：PASS
- `py -3 -m pytest tests/unit/test_phase17_handoff_core.py tests/unit/test_phase17_handoff_policy_router.py tests/unit/test_phase17_handoff_coordinator.py tests/unit/test_phase17_handoff_executor_integration.py tests/unit/test_phase17_handoff_ui_safe_summary.py -q`：17 passed, 3 warnings
- `py -3 -m pytest tests/unit/test_phase16_critic_core.py tests/unit/test_phase16_critic_policy.py tests/unit/test_phase16_critic_engine.py tests/unit/test_phase16_critic_executor_integration.py tests/unit/test_phase16_reflection_ui_safe_summary.py -q`：19 passed, 1 warning
- `py -3 -m pytest tests/unit/test_multi_agent_phase1.py tests/unit/test_multi_agent_phase3_human_approval.py -q`：8 passed, 18 warnings
- `py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py tests/unit/test_phase11_p0_write_gateway.py -q`：13 passed, 7 warnings
- `py -3 -m pytest tests/unit/test_agent_write_requires_confirmation.py tests/unit/test_agent_action_proposal_gateway.py -q`：4 passed
- `py -3 -m pytest tests/unit/test_phase12_context_core.py tests/unit/test_phase12_context_policy.py tests/unit/test_phase12_context_executor_integration.py -q`：8 passed, 2 warnings
- `py -3 -m pytest tests/unit/test_phase13_message_core.py tests/unit/test_phase13_message_store_bus.py tests/unit/test_phase13_message_policy.py -q`：9 passed
- `py -3 -m pytest tests/unit/test_phase14_memory_manager.py tests/unit/test_phase14_memory_tool_ui.py -q`：8 passed
- `py -3 -m pytest tests/unit/test_phase15_observation_core.py tests/unit/test_phase15_replan_policy.py tests/unit/test_phase15_agent_chat_loading.py -q`：14 passed
- `py -3 scripts/check_phase16_reflection_web.py`：PASS
- `py -3 scripts/check_phase15_react_loading_web.py`：PASS
- `py -3 scripts/check_phase13_communication_web.py`：PASS
- `http://127.0.0.1:8501/_stcore/health`：ok

## 真实网页功能检查记录

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = health + Streamlit AppTest scripts + in-app browser real page interaction after restarting 8501

WEB_CHECK_PAGES = ["首页 / 预测排名", "AI Agent", "AI 模拟盘", "系统监控"]

WEB_CHECK_RESULT = PASS

WEB_CHECK_ERRORS = []

检查记录：

| input | actual_summary | handoff_created | roles_seen | handoff_messages_seen | critic_after_handoff_seen | secret_visible | traceback_error | pass/fail |
|---|---|---:|---|---:|---:|---:|---:|---|
| 查看我的当前持仓 | 返回当前模拟盘持仓状态 | false | - | false | true | false | false | PASS |
| 分析当前组合风险 | 页面提交成功，无错误；该轮较慢，后续问题完成后页面仍稳定 | false | - | false | true | false | false | PASS |
| 给我一个调仓建议 | 返回更稳健持仓建议、风险分析、候选证据 | true | EVIDENCE_RETRIEVER, PORTFOLIO_ANALYST, REPORT_WRITER | true | true | false | false | PASS |
| 查看最新报告 | 返回报告记录列表 | false | - | true | true | false | false | PASS |
| 查看系统状态 | 返回当前支持能力说明 | false | - | true | true | false | false | PASS |
| 我上次为什么建议调仓？ | 返回风险、候选证据、调仓边界说明 | true | EVIDENCE_RETRIEVER, PORTFOLIO_ANALYST, REPORT_WRITER | true | true | false | false | PASS |
| 综合分析我的当前持仓风险，并给出是否需要调仓的建议 | 等待后返回稳健持仓建议、风险分析和证据 | true | EVIDENCE_RETRIEVER, PORTFOLIO_ANALYST, REPORT_WRITER | true | true | false | false | PASS |
| 帮我检查这个调仓建议是否证据充分 | 等待后返回基于风险、证据、组合的解释 | true | EVIDENCE_RETRIEVER, PORTFOLIO_ANALYST, REPORT_WRITER | true | true | false | false | PASS |
| 为什么上次建议调仓，分别从风险、证据、组合角度解释 | 返回风险、证据、组合角度解释 | true | EVIDENCE_RETRIEVER, PORTFOLIO_ANALYST, REPORT_WRITER | true | true | false | false | PASS |

页面检查：

- 首页：可打开，免责声明、模型库、每日更新和排名展示可见。
- AI Agent：Handoff caption、Context safe summary、Message trace、Reflection Critic、ReAct trace 可见。
- AI 模拟盘：页面可打开，模拟盘边界和更新入口可见，无真实交易误导。
- 系统监控：`Runtime Reliability`、`MessageBus Health`、`MemoryStore Health`、`ReAct Health`、`Reflection Health`、`Handoff Health` 可见。
- 未发现 `confirmation_token`、API key、数据库路径、本地路径、Traceback、raw payload、raw positions、raw evidence。

备注：浏览器控制台出现的 Statsig 网络超时来自 Codex 浏览器壳层外部埋点请求，不属于本地 8501 应用错误。

## 阶段结论

Phase 17-C 已完成 HandoffCoordinator / SpecialistAdapter 的受控运行时接入、HANDOFF_* MessageBus 记录、Context refs 接入、AI Agent 安全摘要和系统监控 Handoff Health。

NEXT_STAGE_ALLOWED = true
