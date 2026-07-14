# Phase 17-A Handoff 链路审计与 AgentRole 协议设计报告

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## 阶段范围

- 阶段：Phase 17-A / 阶段E，Handoff 链路审计与 AgentRole 协议设计。
- 本阶段只做真实代码审计和协议设计，不接入新的运行时主链路。
- 本阶段未修改业务代码、工具代码、模拟盘算法、审批链路或 UI 行为。

## 真实代码结论

当前项目已经存在轻量 specialist 雏形，但还没有统一的 HandoffRequest / HandoffResult 协议，也没有统一 HandoffRouter。

- 角色定义和工具白名单：`agent/agent_specs.py`
- 旧式 AgentOutput / timeline：`agent/agent_protocol.py`
- 已被主链路调用的 specialist 类：
  - `agent/specialists/market_intelligence.py` / `MarketIntelligenceAgent`
  - `agent/specialists/portfolio_analysis.py` / `PortfolioAnalysisAgent`
  - `agent/specialists/risk_operation.py` / `RiskOperationAgent`
  - `agent/specialists/reporting.py` / `ReportingAgent`
- 主链路调用点：
  - `agent/executor.py::_execute_readonly_multi_agent_collaboration`
  - `agent/executor.py::_execute_position_approval_multi_agent_workflow`
- 并发任务执行和有限 Replan：
  - `agent/orchestration/multi_task_executor.py::execute_multi_intent_plan_async`
- ToolExecutor / 权限边界：
  - `agent/tool_engine.py::ToolDefinition`
  - `agent/tool_engine.py::UnifiedToolExecutor.execute`
- 写入保护链路：
  - `agent/write_gateway.py::execute_confirmed_plan_v2`
  - `agent/tools/write_operation_adapters.py`

## Handoff 链路审计表

| handoff_source | file | function_or_class | current_task_type | candidate_agent_role | handoff_reason | required_context_refs | required_tool_names | requires_memory | requires_approval | contains_secret_risk | can_write_business_state | allowed_operation | blocked_operation | planned_handoff_phase |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| portfolio state 查询 | `agent/executor.py` | `execute_agent_query` -> `portfolio_state` 分支 | read | `PORTFOLIO_ANALYST` | 用户只读查看账户和持仓 | `context_id`, `run_id`, `task_id`, `artifact_refs` | `portfolio_state` | no | no | low | no | 读取账户摘要、持仓摘要 | 暴露 raw_positions、修改持仓 | Phase17-G |
| risk analysis | `agent/executor.py` | `execute_agent_query` -> `portfolio_risk` 分支 | read | `RISK_ANALYST` | 风险检查应与组合读取分离 | `context_id`, `portfolio_artifact_refs`, `observation_refs` | `portfolio_risk` | optional | no | low | no | 读取风险摘要、生成风险 findings | 改仓位、创建确认 token | Phase17-G |
| portfolio proposal | `agent/executor.py` | `_execute_position_approval_multi_agent_workflow` | proposal | `STRATEGY_GUARD` | 调仓建议需要转为确认前预案 | `context_id`, `portfolio_refs`, `market_refs`, `approval_refs` | `portfolio.preview_manual_change` | optional | yes | medium | no | 创建 pending proposal，等待用户确认 | commit、绕过 approval/revalidate | Phase17-G |
| stock/news/RAG evidence 查询 | `agent/specialists/market_intelligence.py` | `MarketIntelligenceAgent.run` | read | `EVIDENCE_RETRIEVER` | 市场证据检索应只读且带来源 | `context_id`, `source_refs`, `artifact_refs` | `ranking`, `stock_news`, `stock_rag`, `stock_analysis`, `mcp.*` read-only | optional | no | medium | no | 检索证据、生成 source refs | 写模拟盘、暴露 raw_evidence、调用 MCP 写工具 | Phase17-G |
| system status | `agent/tools/system_status_tools.py` and `app/pages/system_monitor.py` | system status tools / monitor page | read/system | `SYSTEM_DIAGNOSTIC` | 系统状态检查与业务建议分离 | `run_id`, `message_refs`, `observation_refs` | `system_status`, `scheduler_status`, monitor read tools | no | no | medium | no | 读取健康状态、输出诊断 | 暴露本地路径、数据库路径、内部堆栈 | Phase17-G |
| report generation | `agent/specialists/reporting.py` | `ReportingAgent.run` | report | `REPORT_WRITER` | 汇总其他 specialist 的结构化输出 | `market_message_refs`, `portfolio_message_refs`, `critic_refs` | none | optional | no | low | no | 生成最终可见回答 | 自行调用写工具、改写审批计划 | Phase17-G |
| critic blocking issue | `agent/reflection/critic_engine.py` | `CriticEngine.criticize_final_result` | reflection | `COORDINATOR` | blocking 结果应由 coordinator 停止或改答 | `critic_refs`, `message_refs`, `observation_refs` | none | no | maybe | medium | no | safe block/report, ask user | specialist 直接执行修复写入 | Phase17-G |
| critic handoff hint | `agent/reflection/critic_types.py` and `agent/reflection/critic_policy.py` | `CriticAction.HANDOFF_REQUESTED` / `CriticPolicy.decide_action` | reflection -> route | `COORDINATOR` | 需要将 critic hint 转成受控 HandoffRequest | `critic_refs`, `context_refs`, `message_refs` | role-specific read/proposal tools | optional | depends | medium | no | 只生成 handoff request/result | LLM 自行选择写工具 | Phase17-F/G |
| approval-required proposal | `agent/tool_engine.py` | `ToolDefinition` for proposal/write tools | proposal/write-gated | `STRATEGY_GUARD` -> `COORDINATOR` | proposal 必须等待用户确认，再走 WriteGateway | `approval_refs`, `artifact_refs`, `context_refs` | proposal tools, `approval.confirm_plan` only after confirmed | no | yes | high | only WriteGateway after confirmation | proposal preview / confirmed gateway commit | specialist direct commit、泄露 confirmation_token | Phase17-G |
| multi_task_executor specialist-like outputs | `agent/orchestration/multi_task_executor.py` | `execute_multi_intent_plan_async` | DAG read execution | `COORDINATOR` + role adapters | 现有 DAG 可作为 Handoff 子任务执行底座 | `task_plan_refs`, `observation_refs`, `replan_refs` | read-only tool set | optional | no | medium | no | 并发只读任务、有限 Replan | protected multi-intent、写工具并发执行 | Phase17-G |

## AgentRole 协议设计

建议新增受控角色枚举，不把角色当作自由写状态的独立智能体：

| AgentRole | 职责 | 默认权限 |
|---|---|---|
| `COORDINATOR` | 读取用户目标、创建 HandoffRequest、汇总 HandoffResult、处理 critic action | 不直接写业务状态 |
| `PORTFOLIO_ANALYST` | 读取持仓、账户、组合风险和模拟盘摘要 | read only |
| `RISK_ANALYST` | 检查集中度、一手约束、现金、权限、风险边界 | read only |
| `EVIDENCE_RETRIEVER` | 排名、新闻、RAG、MCP read-only evidence | read only |
| `STRATEGY_GUARD` | 把调仓意图转成确认前 proposal，检查 approval 边界 | proposal only |
| `REPORT_WRITER` | 汇总结构化结果生成用户可见回答 | no tool / read-only refs |
| `SYSTEM_DIAGNOSTIC` | 系统、调度、Runtime、Message、Memory、ReAct、Reflection 健康检查 | read/system only |

规则：

- 所有 role 只能通过 ToolExecutor 或 refs 工作。
- `PORTFOLIO_ANALYST`、`RISK_ANALYST`、`EVIDENCE_RETRIEVER`、`REPORT_WRITER`、`SYSTEM_DIAGNOSTIC` 不能写业务状态。
- `STRATEGY_GUARD` 只能创建确认前 proposal，不能 commit。
- 真实写入只能由 `COORDINATOR` 在用户确认后调用现有 WriteGateway / `approval.confirm_plan`。

## HandoffRequest 字段设计

```text
handoff_id
conversation_id
run_id
task_id
source_role
target_role
reason
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

约束：

- `input_summary` 只允许摘要，不允许 raw payload。
- refs 只传引用和安全摘要，不传 `confirmation_token`、API key、数据库路径、本地路径、内部堆栈、`raw_positions`、`raw_evidence`、`raw_tool_payload`。
- `allowed_tools` 必须由 HandoffPolicy 从 target role 派生，不能由 LLM 任意指定。

## HandoffResult 字段设计

```text
handoff_id
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

约束：

- `status` 建议限制为 `succeeded / failed / skipped / blocked / requires_approval`。
- `recommended_action` 只能表达建议、只读 Replan 或 proposal 建议，不能携带可直接提交的写入 token。
- `errors` / `warnings` 必须经过 sanitizer，不暴露堆栈和本地路径。

## HandoffPolicy 设计

建议实现：

- `tools_for_role(role)`：从统一 ToolDefinition 和 MCP registry 计算白名单。
- `is_tool_allowed(role, tool_name)`：复用 `agent.agent_specs.validate_tool_allowed`，并补上 Phase17 role mapping。
- `can_write_business_state(role)`：除受控 WriteGateway 外全部 false。
- `requires_approval(role, operation_type)`：proposal/write-gated 操作必须 true。
- `classify_visibility(key/path/value)`：复用 MessagePolicy / ContextPolicy / CriticPolicy 风格。
- `validate_request(request)`：检查 target role、allowed tools、blocked tools、敏感字段、refs 格式。
- `validate_result(result)`：检查敏感字段、状态、approval refs、错误摘要。

## HandoffRouter 设计

建议实现：

- `route_from_intent(intent, params, critic_result=None)`：
  - `portfolio_state` -> `PORTFOLIO_ANALYST`
  - `portfolio_risk` -> `RISK_ANALYST`
  - `ranking / stock_news / stock_rag / stock_analysis / mcp.*` -> `EVIDENCE_RETRIEVER`
  - `one_time_position_operation / preview_* / adjust_position` -> `STRATEGY_GUARD`
  - `system_status / scheduler_status` -> `SYSTEM_DIAGNOSTIC`
  - final aggregation -> `REPORT_WRITER`
- `route_from_critic(critic_result)`：
  - `HANDOFF_REQUESTED` -> 根据 `handoff_hint` 和 issue category 选择只读 role
  - `BLOCK_AND_REPORT` -> `COORDINATOR` 直接安全阻断
  - `REQUIRE_APPROVAL` -> `COORDINATOR` 保持等待确认
- `build_request(...)`：只装配 refs 和摘要，不传 raw payload。

## 接入点设计

后续 Phase17-F/G 可最小侵入接入：

- 新增 `agent/handoff/` 包：核心模型、policy、sanitizer、router。
- 在 `agent/executor.py::_execute_readonly_multi_agent_collaboration` 内用 HandoffRequest 包住当前 specialist 顺序调用，但保留当前输出结构。
- 在 `agent/executor.py::_execute_position_approval_multi_agent_workflow` 内将 market -> portfolio -> strategy guard 的手工 timeline 转成 HandoffTrace。
- 在 `_run_phase16_reflection` 后记录 critic handoff hint，但不自动执行写入。
- UI 可先继续展示现有 `agent_timeline`，后续再展示安全 `handoff_trace`。

## 敏感字段风险识别

必须禁止进入 LLM/UI 的字段：

- `confirmation_token`, `confirmation_token_hash`
- `api_key`, `tushare_token`, `authorization`, `password`, `secret`
- `db_path`, `database_path`, `output_dir`, `local_path`, `path`
- `stack`, `stack_trace`, `traceback`, `internal_stack`
- `raw_positions`, `raw_evidence`, `raw_payload`, `raw_tool_payload`, `full_result`

## 测试结果

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts`：PASS
- `py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py tests/unit/test_phase11_p0_write_gateway.py -q`：13 passed, 7 warnings
- `py -3 -m pytest tests/unit/test_agent_write_requires_confirmation.py tests/unit/test_agent_action_proposal_gateway.py -q`：4 passed
- `py -3 -m pytest tests/unit/test_phase12_context_core.py tests/unit/test_phase12_context_policy.py tests/unit/test_phase12_context_executor_integration.py -q`：8 passed, 2 warnings
- `py -3 -m pytest tests/unit/test_phase13_message_core.py tests/unit/test_phase13_message_store_bus.py tests/unit/test_phase13_message_policy.py -q`：9 passed
- `py -3 -m pytest tests/unit/test_phase14_memory_manager.py tests/unit/test_phase14_memory_tool_ui.py -q`：8 passed
- `py -3 -m pytest tests/unit/test_phase15_observation_core.py tests/unit/test_phase15_replan_policy.py tests/unit/test_phase15_agent_chat_loading.py -q`：14 passed
- `py -3 -m pytest tests/unit/test_phase15_replan_executor_integration.py tests/unit/test_phase15_observe_tool_executor_integration.py -q`：6 passed
- `py -3 -m pytest tests/unit/test_phase16_critic_core.py tests/unit/test_phase16_critic_policy.py tests/unit/test_phase16_critic_engine.py tests/unit/test_phase16_critic_executor_integration.py tests/unit/test_phase16_reflection_ui_safe_summary.py -q`：19 passed, 1 warning
- `py -3 scripts/check_phase16_reflection_web.py`：PASS
- `py -3 scripts/check_phase15_react_loading_web.py`：PASS
- `py -3 scripts/check_phase13_communication_web.py`：PASS
- `http://127.0.0.1:8501/_stcore/health`：ok

## 网页检查结果

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = health + Streamlit AppTest scripts + in-app browser real page interaction

WEB_CHECK_PAGES = ["首页 / 预测排名", "AI Agent", "AI 模拟盘", "系统监控"]

WEB_CHECK_RESULT = PASS

WEB_CHECK_ERRORS = []

真实浏览器检查：

- 首页可见模型库、每日更新、排名展示、免责声明。
- AI Agent 页面可见对话区、快捷提问、Context 安全摘要、Message Trace、Reflection Critic、ReAct trace。
- AI Agent 真实输入 `查看当前模拟盘持仓` 后返回持仓状态，未出现 Traceback、内部路径、数据库路径、confirmation_token、API key、raw payload。
- AI 模拟盘页面可见模拟盘说明、策略边界和更新入口，未出现错误或敏感字段。
- 系统监控页面可见总状态、Runtime Reliability、MessageBus Health、MemoryStore Health、ReAct Health、Reflection Health，未出现错误或敏感字段。

备注：浏览器控制台出现的 Statsig 网络超时来自 Codex 浏览器壳层外部埋点请求，不属于本地 8501 应用错误。

## 阶段结论

Phase 17-A 完成了 Handoff 链路审计、AgentRole 设计、HandoffRequest / HandoffResult 设计、Policy / Router 接入点设计和网页基线检查。

NEXT_STAGE_ALLOWED = true
