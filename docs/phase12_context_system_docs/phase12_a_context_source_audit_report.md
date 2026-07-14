# Phase 12-A Context Source Audit Report

## 阶段目标

本阶段只做上下文来源审计与目标设计，不接入主执行链路，不修改 ToolExecutor 行为，不修改 Write Gateway，不修改 UI 逻辑，不修改数据库 schema。

## 修改前状态表

| 项目 | 当前状态 | 问题 | Phase 12 迁移方向 |
| --- | --- | --- | --- |
| 早期上下文模块 | `agent/context/builder.py` 可生成 `BuiltAgentContext.compressed_text` | 主要是压缩文本上下文，不是完整分层 `ContextBundle` | 保留兼容，扩展为 `ContextManager` 分层来源 |
| 工具执行上下文 | `agent/tool_engine.py::ToolExecutor.execute(..., context=dict)` | dict 无可见性策略，LLM/Tool/UI/Audit 边界不统一 | 后续引入 `ToolContext` 与 sanitizer |
| 审批上下文 | `agent/session/confirmation_manager.py` 与 `agent/write_gateway.py` | pending plan 包含 `confirmation_token`，必须禁止进入 LLM | 后续进入 `ApprovalContext`，LLM 只见 token_present/plan_ref |
| Artifact 上下文 | `agent/artifacts.py` 已有脱敏、保存、读取 | Artifact ref 与 report/tool context 尚未统一 | 后续进入 `ArtifactContext` 和 `ContextResolver` |
| UI session_state | `app.py`、`app/pages/ai_agent.py`、`app/pages/ai_paper_trading.py` | 页面状态、token/API key、用户输入混杂在 UI 层 | 后续只抽取 safe page state，不暴露 secret |
| Runtime trace | `agent/runtime.py`、`agent/runtime_reliability.py` | 有 sanitizer，但未纳入统一 ContextPolicy | 后续进入 `RuntimeContext` |

## 上下文来源审计表

| context_source | file | line_or_function | current_usage | data_type | sensitivity | used_by_llm | used_by_tool | used_by_ui | persistence | problem | planned_context_type | migration_phase |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| user_id | `agent/executor.py`, `agent/tool_engine.py`, `app/pages/ai_agent.py` | `run_agent_query`, `ToolExecutor.execute`, page render args | 用户隔离、工具参数、Artifact 归属 | string | internal-id | safe if scoped | yes | yes | db/files/runtime | 当前散落在 dict/session 参数中 | `UserContext.user_id` | B-D |
| conversation_id / session_id | `agent/executor.py`, `agent/artifacts.py`, `database/repositories/agent_repository.py` | run context, artifact save/read | 对话隔离、历史消息读取 | string | internal-id | ref only | yes | yes | database | `session_id` 与 `conversation_id` 并存 | `ConversationContext` | B-D |
| run_id | `agent/runtime.py`, `agent/tool_engine.py`, `agent/artifacts.py` | runtime trace、tool artifact | 执行追踪 | string | internal-id | ref only | yes | yes | database/artifact | 作为裸 dict 传递 | `RuntimeContext.run_id` | B-D |
| task_id | `agent/tool_engine.py`, `agent/orchestration/multi_task_executor.py` | tool artifact task linkage | 子任务追踪 | string | internal-id | ref only | yes | limited | artifact/db | 未形成 TaskContext | `TaskContext.task_id` | B-D |
| session_state | `app.py`, `app/pages/ai_agent.py`, `app/pages/ai_paper_trading.py` | 页面输入、缩放、token 状态、对话状态 | dict | mixed/secret | no raw | no | yes | process session | 可能包含 API key/token，不应进入 LLM | `RuntimeContext.page_state` safe view | E |
| pending confirmation plan | `agent/session/pending_action_store.py`, `agent/session/confirmation_manager.py` | 待确认写操作 | dict | high | summary only | yes | yes | json/db | 原始 plan 含 token 与完整业务预案 | `ApprovalContext.pending_plan_summary` | C-D |
| confirmation_token | `agent/session/confirmation_manager.py`, `agent/write_gateway.py` | 用户确认写操作 | string | secret | never | commit only | masked/present only | pending json | 必须禁止进入 LLM、Artifact summary、UI安全摘要 | `ApprovalContext.token_present` | B-C |
| plan_hash | `agent/session/confirmation_manager.py` | 状态复校和幂等 | string | internal | safe ref | yes | yes | json/db | 应保留但不扩展为业务结论 | `ApprovalContext.plan_hash` | C |
| ToolResult legacy | `agent/tools/tool_schemas.py`, legacy tools | 旧工具返回 | dataclass/dict | mixed | sanitized only | yes | yes | memory/files/logs | 各工具返回形态不一致 | `ToolContext.legacy_result` | D |
| UnifiedToolResult | `agent/tool_engine.py` | v2 工具结果 | dataclass | mixed | sanitized summary | yes | yes | artifact/db | 尚未自动进入 ContextBundle | `ToolContext.result_summary` | C-D |
| Artifact | `agent/artifacts.py::Artifact` | 工具结果持久化 | dataclass/json | sanitized normal | ref/summary only | yes | yes | db/files | 读写规则已有但未统一 resolver | `ArtifactContext` | C |
| Artifact refs | `agent/tool_engine.py`, `agent/artifacts.py` | `artifact_id`, `artifact_ref` | dict/string | normal/internal path risk | id only | yes | yes | db/files | `path` 不应给 LLM | `ArtifactContext.refs` | C |
| Runtime trace | `agent/runtime.py`, `agent/runtime_reliability.py` | run/step/tool_call/checkpoint | dict/db rows | mixed/internal stack risk | summary only | yes | monitor UI | database | trace/error 需要脱敏与裁剪 | `RuntimeContext` | B-D |
| UserProfile | `portfolio/user_profile.py`, `agent/context/gatherer.py` | 用户偏好、约束 | dataclass/dict | personal-ish | summary allowed | yes | yes | db/files | 可给 LLM，但需裁剪 | `UserContext.profile_summary` | B-C |
| Portfolio state | `agent/services/portfolio_service.py`, `portfolio/storage.py`, `agent/context/gatherer.py` | 账户、持仓、订单 | dict/dataclass | financial demo data | summary allowed | yes | yes | files/db | 大对象需窗口裁剪 | `PortfolioContext.state_summary` | B-C |
| Portfolio risk | `agent/services/portfolio_risk_service.py` | 风险等级、集中度、回撤 | dict | financial demo data | summary allowed | yes | yes | computed | 未统一进入 context | `PortfolioContext.risk_summary` | C-D |
| News/RAG evidence | `agent/services/evidence_service.py`, `agent/tools/evidence_adapters.py`, `rag/` | 新闻、chunk、sources | dict/list | normal/source-bound | evidence summary | yes | yes | db/index/artifact | 需要保留 source refs，避免大对象进 prompt | `EvidenceContext` | C-D |
| MCP evidence | `agent/mcp/`, `agent/services/mcp_readonly_client.py` | 只读外部证据 | dict/list | normal/read-only | summary allowed | yes | yes | transient/artifact | 必须继续禁止 MCP 写工具 | `EvidenceContext.mcp_sources` | C-D |
| LLM prompt 拼接内容 | `agent/executor.py`, `agent/router.py`, `llm_explainer.py`, `app.py` | 意图拆解、回答、解释 | string/messages | high mixed | prompt target | no | no | transient/cache | 需要统一 sanitizer/window | `ContextBundle.to_llm_messages()` | B-D |
| page state | `app.py`, `app/pages/*` | 当前页面、缩放、输入框、按钮状态 | dict/session | mixed/secret | safe only | no | yes | session | 页面 state 不应直接成为 Agent prompt | `RuntimeContext.page_state_safe` | E |
| business constraints | `agent/context/gatherer.py::BUSINESS_CONSTRAINTS`, `AGENTS.md` | 免责声明与业务边界 | list[str] | public | yes | yes | yes | code/docs | 现有文本可能有编码历史问题 | `RuntimeContext.business_constraints` | B |
| decomposition / task plan | `agent/intent_decomposition`, `agent/goal_planning.py`, `agent/orchestration/*` | 用户目标、任务、依赖、replan | dataclass/dict | normal/internal | summary allowed | yes | yes | db/artifact | 与上下文窗口未统一 | `TaskContext` | D |
| approval audit tables | `database/repositories/agent_repository.py`, `agent/session/confirmation_manager.py` | action proposals/approvals/commits | db rows | mixed | summary only | yes | monitor UI | database | LLM 不可见 token/raw internals | `ApprovalContext.audit_refs` | C |

## 目标 ContextBundle 设计草案

| Context type | 核心字段 | 来源 | 可给 LLM | 可给 Tool | 可给 UI | 可 audit | 裁剪 | 脱敏 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `UserContext` | `user_id`, `profile_summary`, `constraints` | UI、profile repo | yes, summary | yes | yes | yes | yes | yes |
| `ConversationContext` | `conversation_id`, `recent_messages`, `language` | AgentRepository, UI | yes, sanitized history | yes | yes | yes | yes | yes |
| `TaskContext` | `run_id`, `task_id`, `user_goal`, `task_plan`, `dependencies` | goal planner/orchestrator | yes, summary | yes | yes | yes | yes | yes |
| `ToolContext` | `allowed_tools`, `tool_name`, `arguments`, `result_summary` | ToolRegistry/ToolExecutor | limited | yes | safe result | yes | yes | yes |
| `PortfolioContext` | `account_summary`, `positions_summary`, `risk_summary` | PortfolioService/RiskService | yes, summary | yes, full by permission | yes | yes | yes | yes |
| `EvidenceContext` | `evidence_refs`, `source_summaries`, `mcp_sources` | EvidenceService/RAG/MCP | yes, cited summary | yes | yes | yes | yes | yes |
| `ArtifactContext` | `artifact_refs`, `produced_outputs`, `readable_ids` | ArtifactStore | refs/summary only | yes, resolver full read | yes | yes | yes | yes |
| `ApprovalContext` | `plan_id`, `plan_hash`, `token_present`, `status`, `safe_plan_summary` | confirmation manager | no raw token | yes for gateway | yes safe | yes | yes | mandatory |
| `RuntimeContext` | `run_id`, `phase`, `budget`, `warnings`, `business_constraints` | runtime/reliability/app | yes safe | yes | yes | yes | yes | yes |
| `MemoryContext` | `memory_refs`, `placeholder_only` | existing layered memory | minimal summary only | yes later | limited | yes | yes | yes |

## 设计接入点

| 接入点 | 计划 |
| --- | --- |
| Initial context | `ContextManager.create_initial_context()` 从 user/session/run/page safe state 构造 `ContextBundle`。 |
| LLM prompt | `ContextPolicy` + `ContextSanitizer` + `ContextWindow` 输出 LLM-safe dict/messages。 |
| Tool execution | `ContextManager.build_tool_context()` 保持旧 dict 兼容，同时可提供 `ToolContext`。 |
| Tool result update | `ContextManager.update_from_tool_result()` 将 `UnifiedToolResult` 和 `artifact_ref` 写入 `ToolContext/ArtifactContext`。 |
| Artifact reuse | `ContextResolver` 只暴露 artifact id/summary 给 LLM，工具按 user/conversation/run 权限读取完整内容。 |
| Approval | `ApprovalContext` 永远隐藏 `confirmation_token` 原文，只保留 `token_present`、`plan_id`、`plan_hash`。 |
| UI | 仅显示 safe fields；后续阶段 E 再做小范围页面接入。 |

## 安全策略

- `confirmation_token`、`confirmation_token_hash`、`api_key`、`llm_api_key`、`tushare_token`、`authorization`、`cookie`、`password`、`secret`、数据库路径、内部文件路径、内部 traceback 默认禁止进入 LLM view。
- Tool view 可按权限保留必要字段，但写操作仍必须经过 `execute_confirmed_plan_v2` 和 v2 approval-required ToolDefinition。
- UI view 只显示 safe summary，不显示 token 原文。
- Audit view 可保留内部 trace，但仍需 mask secret。

## 兼容策略

- 保留 `agent.context.build_agent_context()` 与 `BuiltAgentContext`，后续作为 `ContextBundle` 的 legacy/minimal compressed view。
- 保留 `ToolExecutor.execute(..., context=dict)`，后续只新增可选 `ContextBundle`/`ToolContext` 转换，不破坏旧调用。
- 保留 UI 现有 `st.session_state`，后续只抽取 safe page state。
- 不删除旧工具、不改变 P0/P1-A/P2 业务路径。

## 修改文件

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `docs/phase12_a_context_source_audit_report.md` | 新增 | 上下文来源审计、目标设计、阶段测试与网页检查报告。 |

## 测试命令与结果

| 命令 | 结果 |
| --- | --- |
| `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts` | pass |
| `py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q` | 7 passed |
| `py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q` | 6 passed |
| `py -3 -m pytest tests/unit/test_phase10_goal_planning.py -q` | 13 passed |
| `py -3 -m pytest tests/unit/test_phase10_3_capability_artifacts.py -q` | 9 passed |

Known warnings: existing `datetime.utcnow()` deprecation warnings in `agent/capability_index.py`.

## 真实网页检查

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = playwright

WEB_CHECK_PAGES = [`http://127.0.0.1:8501/_stcore/health`, `首页 / 预测排名`, `AI Agent`, `AI 模拟盘`, `系统监控`]

WEB_CHECK_RESULT = pass

WEB_CHECK_ERRORS = []

检查摘要：

| 页面 | 关键功能 | 结果 |
| --- | --- | --- |
| health | `_stcore/health` -> `ok` | pass |
| 首页 / 预测排名 | 标题、免责声明、模型库管理、手动生成预测排名、每日更新并生成预测排名 | pass |
| AI Agent | 控制中心、对话输入、清空对话、快捷提问 | pass |
| AI 模拟盘 | 页面标题、更新入口、用户与账户摘要、持仓、资金、风险、订单 | pass |
| 系统监控 | 页面标题、总状态、保存监控快照、Runtime Reliability | pass |

未发现：Traceback、ModuleNotFoundError、NameError、KeyError、Unhandled exception、页面乱码。

## 失败项

无。

## 未完成项

- 尚未实现 `ContextBundle` 分层模型。
- 尚未实现 `ContextPolicy`、`ContextSanitizer`、`ContextWindow`。
- 尚未接入 Executor / ToolExecutor / UI。

这些内容按阶段 B-F 执行。

NEXT_STAGE_ALLOWED = true
