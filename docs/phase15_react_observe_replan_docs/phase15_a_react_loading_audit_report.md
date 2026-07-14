# Phase 15-A ReAct Loading Audit Report

## 阶段目标

审计当前项目中可生成 Observation、可触发 Replan、可接入 MessageBus/Context/Memory 的真实代码路径，并建立 AI Agent 页面加载性能基线。本阶段未接入完整 ReAct 主链，未修改业务逻辑。

## 修改前状态表

| 检查项 | 当前状态 | 证据 |
|---|---|---|
| ToolExecutor 结果 | 已统一为 `UnifiedToolResult`，并发布 `TOOL_CALL_REQUESTED`、`TOOL_RESULT_RECEIVED`、`ERROR_RAISED`、`APPROVAL_REQUESTED` 消息 | `agent/tool_engine.py:326`, `agent/tool_engine.py:435`, `agent/tool_engine.py:502`, `agent/tool_engine.py:514` |
| Executor 主链 | 创建 ContextBundle，发布 USER/CONTEXT/GOAL/TASK/FINAL 消息，最后更新 ContextBundle | `agent/executor.py:2580`, `agent/executor.py:2589`, `agent/executor.py:2827`, `agent/executor.py:2845`, `agent/executor.py:3439`, `agent/executor.py:3593` |
| 现有观察逻辑 | `multi_task_executor` 有 dict 型 observation 和有限 replan，但不是标准 ObservationEvent/ObserveStore | `agent/orchestration/multi_task_executor.py:710`, `agent/orchestration/multi_task_executor.py:1524`, `agent/orchestration/multi_task_executor.py:1771` |
| Message 协议 | 已有 `OBSERVATION_CREATED`，但没有 `REPLAN_REQUESTED/APPLIED/SKIPPED` | `agent/communication/message_types.py:39` |
| Runtime 状态 | 已有 observing/replanning 状态常量和状态转换表 | `agent/runtime.py:17`, `agent/runtime.py:48` |
| Context | 已有 memory refs、artifact refs、approval context 和 sanitizer/window | `agent/context/context_builder.py:45`, `agent/context/context_types.py:108`, `agent/context/context_types.py:119`, `agent/context/context_types.py:147` |
| Memory | MemoryTool 只读，UI 仅显示 safe summary | `agent/tool_engine.py:978`, `agent/tool_engine.py:1009`, `app/pages/ai_agent.py:1118` |
| AI Agent 加载 | 已有缓存和性能指标，但默认加载 50 条消息并对每条消息渲染 result details | `app/pages/ai_agent.py:201`, `app/pages/ai_agent.py:791`, `app/pages/ai_agent.py:1283`, `app/pages/ai_agent.py:1637` |

## ReAct 链路审计表

| source | file | function_or_class | current_input | current_output | can_create_observation | planned_observation_type | can_trigger_replan | planned_replan_reason | contains_context | contains_artifact_ref | contains_tool_result | contains_memory_ref | contains_approval | contains_secret_risk | used_by_llm | used_by_ui | problem | migration_phase |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| user request | `agent/executor.py` | `run_agent_request` | query/top_k/user/session | `USER_REQUEST` message, runtime run | yes | CONTEXT_INSUFFICIENT | yes | missing_required_context | yes | no | no | yes | maybe | low | yes | yes | no standard observation yet | D |
| ContextBundle | `agent/context/context_builder.py` | `ContextManager.create_initial_context` | user/query/run/page state | ContextBundle, memory refs | yes | CONTEXT_INSUFFICIENT/MEMORY_HIT/MEMORY_EMPTY | yes | max_context_budget_exceeded | yes | yes | no | yes | yes | low after sanitizer | yes | partly | observation refs missing | D |
| TaskPlan | `agent/goal_planning.py` | `build_goal_planning_trace` | decomposition/context | semantic goal/task plan | yes | TASK_PARTIAL_SUCCESS/TASK_FAILED | yes | missing_required_parameter | yes | yes | no | yes | yes | medium if raw context leaks | yes | yes | plan validation not normalized to ObservationEvent | D |
| ToolExecutor input | `agent/tool_engine.py` | `ToolExecutor.execute` | tool_name/arguments/context | call messages and result | yes | TOOL_PERMISSION_BLOCKED/APPROVAL_REQUIRED | yes | permission_blocked/approval_required | yes | yes | yes | yes | yes | arguments may contain token | no | yes via result | observation created only as MessageType error/result today | D |
| UnifiedToolResult | `agent/tool_engine.py` | `UnifiedToolResult` | normalized handler result | success/message/data/errors/artifact | yes | TOOL_SUCCESS/TOOL_ERROR/TOOL_EMPTY_RESULT | yes | tool_error_recoverable/tool_result_empty | yes | yes | yes | no | maybe | raw data can be large | yes through summaries | yes | needs sanitizer + refs only | B-D |
| Artifact refs | `agent/artifacts.py` | `save_tool_result_artifact` | tool result | artifact ref | yes | TOOL_SUCCESS | no | n/a | yes | yes | yes | no | maybe | artifact path risk | no | yes | path must stay audit-only | B-D |
| Approval pending plan | `agent/tool_engine.py` | approval requested branch | plan_id/hash/status/token_present | APPROVAL_REQUESTED | yes | APPROVAL_REQUIRED | yes | approval_required | yes | no | yes | no | yes | confirmation token risk | yes summary only | yes | token must never enter LLM/UI | B-D |
| confirmation result | `agent/write_gateway.py` | `execute_confirmed_plan_v2` | plan_id/token/user | commit result and APPROVAL_RESULT_RECEIVED | yes | APPROVAL_DENIED/TASK_FAILED/REPORT_READY | yes | approval_denied/task_dependency_failed | yes | yes | yes | no | yes | token risk | no token | yes | replan must not bypass gateway | D |
| MessageTrace | `agent/communication/message_trace.py` | `build_message_trace` | AgentMessage list | trace edges/errors/warnings | yes | TASK_PARTIAL_SUCCESS/TASK_FAILED | yes | task_dependency_failed | yes | yes | yes | no | yes | raw trace risk handled by sanitizer | yes summary | yes | no ReActTrace yet | C |
| MemoryTool summary | `agent/memory/memory_tool.py` | `memory_search_adapter`, `memory_get_summary_adapter` | query/user/output_dir | safe memory items/health | yes | MEMORY_HIT/MEMORY_EMPTY | yes | missing_required_context | yes | no | no | yes | no | low after sanitizer | yes | yes | readonly boundary must stay explicit | D-E |
| warnings/errors | `agent/tool_engine.py` | `_failure`, ERROR_RAISED messages | error type/message | UnifiedToolResult failure | yes | TOOL_ERROR/TOOL_PERMISSION_BLOCKED | yes | tool_error_recoverable/permission_blocked | yes | maybe | yes | no | maybe | stack risk if raw exception | yes if sanitized | yes | needs ObserveSanitizer | B-D |
| AI Agent page result rendering | `app/pages/ai_agent.py` | `_render_result_details` | `agent_result` | context/message trace/tool details expanders | yes | REPORT_READY/TASK_PARTIAL_SUCCESS | no | n/a | yes | yes | yes | yes | yes | raw result display risk mitigated by redactor | no | yes | default renders expander objects for every loaded message | E |
| AI Paper Trading page | `app/pages/ai_paper_trading.py` | page renderer | account/paper state | UI tables/actions | yes | TASK_PARTIAL_SUCCESS/TASK_FAILED | no | n/a | no | no | maybe | no | maybe | low | no | yes | should only consume summarized observations | F |
| multi_task_executor result passing | `agent/orchestration/multi_task_executor.py` | `_observe_task_results`, replan block | task_results/tool_calls | dict observations/replan_audit | yes | TOOL_EMPTY_RESULT/EVIDENCE_INSUFFICIENT/TASK_FAILED | yes | tool_result_empty/evidence_insufficient/task_dependency_failed | yes | maybe | yes | no | maybe | medium raw dict | yes through final result | yes | existing logic is useful but not standard model/store | C-D |
| specialist agent result passing | `agent/specialists/` | specialist outputs | structured specialist task input | specialist result | yes | TASK_PARTIAL_SUCCESS/REPORT_READY | maybe | task_dependency_failed | yes | maybe | yes | maybe | maybe | depends on payload | yes | yes | must not name tool functions as agents in final ReAct trace | D-F |

## 加载性能基线表

| page | component | current_loading_strategy | query_count_estimate | render_count_estimate | rerun_sensitive | loads_full_history | loads_full_trace | loads_full_memory | loads_raw_tool_details | symptom | planned_optimization | migration_phase |
|---|---|---:|---:|---:|---|---|---|---|---|---|---|---|
| AI Agent | 历史消息列表 | cached recent messages, default limit 50 | 1 on cache miss | one chat card per loaded message | yes | partial but too large | per message summary | no | result details expander per message | after 7-12 messages markdown/json counts rise | default 8-10 window + load earlier | E |
| AI Agent | 当前输入框 | Streamlit `chat_input` | 0 | 1 | yes | no | no | no | no | stable | keep unchanged | E |
| AI Agent | message trace 展示 | built from last result / run logs, shown per message details | 0-1 when result present | expander per result | yes | no | summary only | no | no | repeated expanders grow with message count | show summary only for recent/current result, lazy older trace | E |
| AI Agent | developer details | collapsed expander, checkbox lazy loads JSON | 0 until checkbox | small when collapsed | yes | no | no | safe summary only | yes after checkbox | acceptable but still displays perf json | keep collapsed, move heavy JSON behind checkbox | E |
| AI Agent | tool details | expander around redacted full result | 0 | one JSON per result | yes | no | yes if loaded result contains trace | no | yes redacted | JSON count grows: 5 at msg1, 23 at msg7, 38 at msg12 | lazy per latest result, summaries for older messages | E |
| AI Agent | evidence details | included in result JSON when present | 0 | tied to tool details | yes | no | no | no | potentially | raw evidence must not show | artifact/source refs only | D-E |
| AI Agent | memory summary | `build_memory_safe_summary` caption in developer details | 1 lightweight count | 1 | low | no | no | no full records | no | safe and light | keep summary only, cache short TTL | E |
| 系统监控 | MemoryStore health | aggregate counts | 1-3 small store reads | one dataframe | low | no | no | summary only | no | acceptable | keep aggregate only | F |
| 系统监控 | MessageBus health | latest run jsonl summary | filesystem scan + one run read | one dataframe | low | latest run only | summary only | no | no | acceptable | keep summary only | F |
| AI 模拟盘 | 页面 | portfolio/account data render | several data reads | tables/charts | medium | no | no | no | no | current check passes | do not touch in Phase15 unless regression fails | F |

## Observation 目标模型

- `ObservationEvent`: observation_id, run_id, task_id, tool_name, observation_type, status, severity, summary, evidence_refs, artifact_refs, context_refs, memory_refs, approval_refs, error_type, replan_hint, created_at, metadata.
- `ObservationType`: TOOL_SUCCESS, TOOL_EMPTY_RESULT, TOOL_ERROR, TOOL_PERMISSION_BLOCKED, CONTEXT_INSUFFICIENT, EVIDENCE_INSUFFICIENT, MEMORY_HIT, MEMORY_EMPTY, APPROVAL_REQUIRED, APPROVAL_DENIED, TASK_PARTIAL_SUCCESS, TASK_FAILED, REPORT_READY.
- `ObservationStatus`: CREATED, ACCEPTED, IGNORED, REPLAN_REQUESTED, RESOLVED.
- `ObservationSeverity`: INFO, WARNING, ERROR, CRITICAL.
- `ObservePolicy`: deterministic rules mapping tool/result/context state to observation type/severity/replan hint.
- `ObserveSanitizer`: redacts confirmation_token, API keys, db paths, local paths, stack traces, raw_positions, raw_evidence, raw_tool_payload.
- `ObserveStore`: append-only local store under outputs, audit-safe payload only.
- `ReActStep`: thought/action/observation/replan refs without raw prompt or secrets.
- `ReActTrace`: run-level ordered steps and observation refs.

## Replan 目标模型

- `ReplanDecision`: APPLY, SKIP, BLOCK, WAIT_APPROVAL.
- `ReplanReason`: missing_required_context, missing_required_parameter, tool_error_recoverable, tool_result_empty, evidence_insufficient, permission_blocked, approval_required, user_goal_changed, task_dependency_failed, max_context_budget_exceeded.
- `ReplanScope`: TASK, SUBGRAPH, PLAN, REPORT_ONLY.
- `ReplanPolicy`: max rounds, max new steps, readonly-only for auto replan, no commit, no approval bypass, no WriteGateway bypass.

## 风险点

- Tool arguments and approval flows can contain `confirmation_token`; observations must store only `token_present`.
- Tool results can contain raw evidence, raw positions or large JSON; observations must store summary + refs.
- Artifact paths and DB paths must be audit-only and never appear in LLM/UI messages.
- Existing dict observations in `multi_task_executor` are useful but not sanitized as a standalone ObservationEvent.
- AI Agent currently renders result details for every loaded message; this is the likely reason long conversations degrade.

## 加载瓶颈判断

Long-chat baseline:

- Initial render: 5150.865 ms.
- Message 1: 1696.446 ms, markdown=6, caption=7, json=5.
- Message 7: 2225.468 ms, markdown=18, caption=19, json=23.
- Message 12: 2915.684 ms, markdown=28, caption=29, json=38.
- Average message submit: 2238.824 ms.
- Max message submit: 3294.178 ms.
- Refresh render with same temp DB: 83.459 ms in AppTest, refresh markdown=4, caption=5, json=1.

Diagnosis: submit-time reruns accumulate per-message result detail JSON/expander rendering. Default message limit is 50, so real persisted long conversations can render far more than the 12-message baseline.

## 新增/修改文件

- Added `docs/phase15_a_react_loading_audit_report.md`
- No business code changed in Phase 15-A.

## Observation 类型

Designed only in this phase: TOOL_SUCCESS, TOOL_EMPTY_RESULT, TOOL_ERROR, TOOL_PERMISSION_BLOCKED, CONTEXT_INSUFFICIENT, EVIDENCE_INSUFFICIENT, MEMORY_HIT, MEMORY_EMPTY, APPROVAL_REQUIRED, APPROVAL_DENIED, TASK_PARTIAL_SUCCESS, TASK_FAILED, REPORT_READY.

## ObservePolicy 规则

Designed only in this phase:

- failed tool result -> TOOL_ERROR or TOOL_PERMISSION_BLOCKED.
- success with empty required data -> TOOL_EMPTY_RESULT.
- RAG/news without sources -> EVIDENCE_INSUFFICIENT.
- context missing required refs/parameters -> CONTEXT_INSUFFICIENT.
- memory search with hits -> MEMORY_HIT; no hits -> MEMORY_EMPTY.
- plan_id/approval request -> APPROVAL_REQUIRED.

## ReplanPolicy 规则

Designed only in this phase:

- Auto replan may add readonly evidence/fallback tasks only.
- Auto replan cannot call write tools and cannot bypass approval.
- Max rounds and max new steps must be enforced.
- Approval-required observations produce WAIT_APPROVAL, not commit.

## MessageBus 接入点

- Existing: USER_REQUEST, CONTEXT_CREATED, GOAL_PARSED, TASK_PLANNED, TOOL_CALL_REQUESTED, TOOL_RESULT_RECEIVED, APPROVAL_REQUESTED, APPROVAL_RESULT_RECEIVED, ERROR_RAISED, FINAL_REPORT.
- Existing enum only: OBSERVATION_CREATED.
- Missing for Phase15 implementation: REPLAN_REQUESTED, REPLAN_APPLIED, REPLAN_SKIPPED.

## ContextManager 接入点

- `ContextManager.create_initial_context` creates memory refs and metadata.
- `ContextManager.update_from_tool_result` can attach artifact refs from tool results.
- Planned: add observation refs to runtime context, not raw observation payloads.

## ToolExecutor 接入点

- `ToolExecutor.execute` is the best single point to create observations from `UnifiedToolResult`.
- Existing failure branches can map to TOOL_PERMISSION_BLOCKED, APPROVAL_REQUIRED, TOOL_ERROR.
- Existing output validation can map to TOOL_EMPTY_RESULT or TOOL_ERROR.

## WriteGateway 边界说明

- `execute_confirmed_plan_v2` remains the confirmed write gateway.
- Replan must not call commit tools directly.
- Observations may reference approval status but must not store or expose confirmation token.

## MemoryTool readonly 边界说明

- `memory.search` and `memory.get_summary` remain read-only and return `not_committed=true`.
- Memory summary is safe aggregate UI text only.

## AI Agent 加载优化结果

This stage is audit-only. No UI optimization was applied yet. Baseline shows result detail rendering grows with conversation length and should be optimized in Phase 15-E.

## 兼容旧接口说明

No code paths were removed. Existing dict result paths, Phase 13 messages, Phase 14 memory interfaces, and AI Agent session state behavior remain unchanged.

## 测试命令与结果

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts` -> PASS
- `py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py tests/unit/test_phase11_p0_write_gateway.py -q` -> PASS, 13 passed
- `py -3 -m pytest tests/unit/test_phase12_context_core.py tests/unit/test_phase12_context_policy.py tests/unit/test_phase12_context_executor_integration.py -q` -> PASS, 8 passed
- `py -3 -m pytest tests/unit/test_phase13_message_core.py tests/unit/test_phase13_message_store_bus.py -q` -> PASS, 6 passed
- `py -3 -m pytest tests/unit/test_phase14_memory_manager.py tests/unit/test_phase14_memory_tool_ui.py -q` -> PASS, 8 passed

## 真实网页检查方法

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = health endpoint + `scripts/check_phase13_communication_web.py` + Playwright Chromium real render + in-app browser inspection + Streamlit AppTest long-chat baseline

WEB_CHECK_PAGES = [
  "http://127.0.0.1:8501/_stcore/health",
  "首页 / 预测排名",
  "AI Agent 页面",
  "AI 模拟盘页面",
  "系统监控页面"
]

WEB_CHECK_RESULT = PASS

WEB_CHECK_ERRORS = []

LONG_CHAT_CHECK_DONE = true

LONG_CHAT_MESSAGE_COUNT = 12

LOAD_BASELINE_SUMMARY = "message_1=1696.446ms, message_7=2225.468ms, message_12=2915.684ms, avg=2238.824ms, max=3294.178ms; no visible Traceback/NameError/KeyError/secret markers"

## 失败项

- None.

## 未完成项

- Standard ObservationEvent, ObserveStore, ReActTrace and ReplanPolicy are designed but not implemented in Phase 15-A by requirement.
- AI Agent loading optimization is measured but not applied in Phase 15-A by requirement.

NEXT_STAGE_ALLOWED = true
