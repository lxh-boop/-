# Phase 17-B Handoff 核心模型、Router、Policy、Sanitizer 报告

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## 阶段范围

- 阶段：Phase 17-B / 阶段F。
- 本阶段新增 Handoff 核心模型、路由规则、安全策略和脱敏器。
- 本阶段未接入 executor 主链，未修改 ToolExecutor / WriteGateway / ContextManager / MemoryManager。
- Specialist 仍不能直接写业务状态。

## 新增文件

- `agent/handoff/__init__.py`
- `agent/handoff/handoff_types.py`
- `agent/handoff/handoff_policy.py`
- `agent/handoff/handoff_sanitizer.py`
- `agent/handoff/handoff_router.py`
- `tests/unit/test_phase17_handoff_core.py`
- `tests/unit/test_phase17_handoff_policy_router.py`

## HandoffRequest 模型

实现位置：`agent/handoff/handoff_types.py::HandoffRequest`

字段：

```text
handoff_id
conversation_id
run_id
task_id
source_role
target_role
reason
priority
input_summary
context_refs
message_refs
observation_refs
replan_refs
critic_refs
memory_refs
artifact_refs
approval_refs
allowed_tools
blocked_tools
requires_approval
created_at
metadata
```

能力：

- `to_dict()`
- `from_dict()`
- `AgentRole` / `HandoffPriority` 自动归一化
- refs / tools / metadata 归一化

## HandoffResult 模型

实现位置：`agent/handoff/handoff_types.py::HandoffResult`

字段：

```text
handoff_id
conversation_id
run_id
task_id
target_role
status
summary
findings
recommended_action
artifact_refs
message_refs
observation_refs
critic_refs
approval_refs
errors
warnings
created_at
metadata
```

能力：

- `to_dict()`
- `from_dict()`
- `AgentRole` / `HandoffStatus` 自动归一化
- 只承载结构化结果，不执行工具、不写状态。

## AgentRole 列表

实现位置：`agent/handoff/handoff_types.py::AgentRole`

- `COORDINATOR`
- `PORTFOLIO_ANALYST`
- `RISK_ANALYST`
- `EVIDENCE_RETRIEVER`
- `STRATEGY_GUARD`
- `REPORT_WRITER`
- `SYSTEM_DIAGNOSTIC`

兼容映射：

- `supervisor` -> `COORDINATOR`
- `market_intelligence` -> `EVIDENCE_RETRIEVER`
- `portfolio_analysis` -> `PORTFOLIO_ANALYST`
- `risk_operation` -> `STRATEGY_GUARD`
- `reporting` -> `REPORT_WRITER`

## HandoffTrace

实现位置：`agent/handoff/handoff_types.py::HandoffTrace`

字段：

```text
trace_id
run_id
handoff_ids
role_edges
tool_edges
artifact_edges
critic_edges
approval_edges
errors
warnings
```

`add_request()` 会从 `HandoffRequest` 中追加 role/tool/artifact/critic/approval 边，供后续运行时接入和 UI 安全摘要使用。

## HandoffPolicy 规则

实现位置：`agent/handoff/handoff_policy.py::HandoffPolicy`

已实现方法：

- `can_handoff()`
- `allowed_tools_for_role()`
- `blocked_tools_for_role()`
- `requires_approval()`
- `can_show_to_llm()`
- `can_show_to_ui()`
- `max_handoff_depth()`
- `validate_request()`
- `contains_sensitive_data()`
- `can_write_business_state()`

关键边界：

- `PORTFOLIO_ANALYST`：可读 `portfolio_state`、`portfolio_risk`、`position_recommendation`，不能写。
- `RISK_ANALYST`：可读风险和持仓摘要，不能改策略。
- `EVIDENCE_RETRIEVER`：可读 ranking/news/RAG/MCP read-only evidence，不能写持仓。
- `STRATEGY_GUARD`：可用 proposal 工具生成确认前预案，不能 commit。
- `REPORT_WRITER`：只汇总 refs，不调用写工具。
- `SYSTEM_DIAGNOSTIC`：只读系统状态。
- 写工具如 `approval.confirm_plan`、`paper_trade_execute`、`strategy_confirmation_execute`、`capital_management_execute`、`backfill_execute` 不会出现在 specialist allowed tools 中。

## HandoffRouter 规则

实现位置：`agent/handoff/handoff_router.py::HandoffRouter`

已实现方法：

- `route_by_user_goal()`
- `route_by_critic_action()`
- `route_by_missing_context()`
- `route_by_tool_need()`
- `route_by_risk_level()`
- `build_request()`

路由示例：

- 证据不足 / RAG / 新闻 / 排名 -> `EVIDENCE_RETRIEVER`
- 当前持仓 / 账户 / 组合 -> `PORTFOLIO_ANALYST`
- 风险 / 集中度 / 回撤 -> `RISK_ANALYST`
- 调仓 / 加仓 / 减仓 / proposal -> `PORTFOLIO_ANALYST` + `RISK_ANALYST` + `STRATEGY_GUARD`
- 系统状态 / 调度 / Runtime -> `SYSTEM_DIAGNOSTIC`
- 最终汇总 -> `REPORT_WRITER`
- `CriticAction.HANDOFF_REQUESTED` 根据 `handoff_hint` 路由
- `CriticAction.BLOCK_AND_REPORT` / `REQUIRE_APPROVAL` -> `COORDINATOR`

## HandoffSanitizer 结果

实现位置：`agent/handoff/handoff_sanitizer.py::HandoffSanitizer`

已实现：

- `sanitize_for_llm()`
- `sanitize_for_ui()`
- `sanitize_for_audit()`
- `sanitize_request()`
- `sanitize_result()`
- `sanitize_handoff()`

过滤字段和内容：

- `confirmation_token`
- `api_key`
- `tushare_token`
- `password`
- `secret`
- `db_path`
- local path / Windows path
- stack trace / Traceback
- `raw_positions`
- `raw_evidence`
- `raw_payload`
- `raw_tool_payload`
- private chain-of-thought / internal reasoning

## 测试结果

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts`：PASS
- `py -3 -m pytest tests/unit/test_phase17_handoff_core.py tests/unit/test_phase17_handoff_policy_router.py -q`：10 passed
- `py -3 -m pytest tests/unit/test_phase16_critic_core.py tests/unit/test_phase16_critic_policy.py -q`：8 passed
- `py -3 -m pytest tests/unit/test_phase16_critic_engine.py tests/unit/test_phase16_critic_executor_integration.py tests/unit/test_phase16_reflection_ui_safe_summary.py -q`：11 passed, 1 warning
- `py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py tests/unit/test_phase11_p0_write_gateway.py -q`：13 passed, 7 warnings
- `py -3 -m pytest tests/unit/test_agent_write_requires_confirmation.py tests/unit/test_agent_action_proposal_gateway.py -q`：4 passed
- `py -3 -m pytest tests/unit/test_phase12_context_core.py tests/unit/test_phase12_context_policy.py tests/unit/test_phase12_context_executor_integration.py -q`：8 passed, 2 warnings
- `py -3 -m pytest tests/unit/test_phase13_message_core.py tests/unit/test_phase13_message_store_bus.py tests/unit/test_phase13_message_policy.py -q`：9 passed
- `py -3 -m pytest tests/unit/test_phase14_memory_manager.py tests/unit/test_phase14_memory_tool_ui.py -q`：8 passed
- `py -3 -m pytest tests/unit/test_phase15_observation_core.py tests/unit/test_phase15_replan_policy.py tests/unit/test_phase15_agent_chat_loading.py -q`：14 passed
- `py -3 scripts/check_phase16_reflection_web.py`：PASS
- `py -3 scripts/check_phase15_react_loading_web.py`：PASS
- `http://127.0.0.1:8501/_stcore/health`：ok

## 网页检查结果

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = health + Streamlit AppTest scripts + in-app browser real page interaction

WEB_CHECK_PAGES = ["首页 / 预测排名", "AI Agent", "AI 模拟盘", "系统监控"]

WEB_CHECK_RESULT = PASS

WEB_CHECK_ERRORS = []

真实浏览器检查：

- 首页可打开，模型库、每日更新、排名展示和免责声明可见。
- AI Agent 页面可打开。
- AI Agent 连续真实输入并返回可见回答：
  - `查看我的当前持仓`
  - `分析当前组合风险`
  - `给我一个调仓建议`
  - `查看最新报告`
  - `查看系统状态`
  - `我上次为什么建议调仓？`
- 每次回答后可见 Context safe summary、Message trace、Reflection Critic。
- AI 模拟盘页面可打开，模拟盘边界和更新入口可见。
- 系统监控页面可打开，Runtime Reliability、MessageBus Health、MemoryStore Health、ReAct Health、Reflection Health 可见。
- 未发现 Traceback、内部路径、数据库路径、API key、confirmation_token、raw payload、raw positions、raw evidence。

备注：浏览器控制台出现的 Statsig 网络超时来自 Codex 浏览器壳层外部埋点请求，不属于本地 8501 应用错误。

## 阶段结论

Phase 17-B 已建立 Handoff 核心模型、Router、Policy 和 Sanitizer，并验证 specialist 不能直接写业务状态、敏感字段不会进入 LLM/UI。

NEXT_STAGE_ALLOWED = true
