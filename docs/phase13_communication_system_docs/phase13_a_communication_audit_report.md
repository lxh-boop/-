# Phase 13-A Communication Audit Report

## Stage Goal

Phase 13-A audits the current communication path and designs the target AgentMessage / MessageBus protocol. No runtime code, UI logic, database schema, ToolExecutor behavior, WriteGateway behavior, or ContextManager behavior was changed in this stage.

## Stage Scope Output Before Work

- 本阶段目标: inspect existing dict/result/context/approval/artifact/UI communication and define the target message protocol.
- 本阶段禁止事项: no Executor integration, no ToolExecutor behavior change, no WriteGateway change, no ContextManager change, no UI change, no DB schema change, no MemoryManager/ReAct/Reflection/Multi-Agent Handoff implementation.
- 需要检查的文件:
  - `agent/executor.py`
  - `agent/tool_engine.py`
  - `agent/write_gateway.py`
  - `agent/context/`
  - `agent/artifacts.py`
  - `agent/runtime.py`
  - `agent/runtime_reliability.py`
  - `agent/goal_planning.py`
  - `agent/intent_decomposition/`
  - `agent/orchestration/multi_task_executor.py`
  - `agent/specialists/`
  - `agent/tools/`
  - `agent/services/`
  - `app/pages/ai_agent.py`
  - `app/pages/ai_paper_trading.py`
  - `app.py`
- 预计新增/修改文件:
  - added `docs/phase13_a_communication_audit_report.md`
- 测试命令:
  - `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts`
  - `py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q`
  - `py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q`
  - `py -3 -m pytest tests/unit/test_phase12_context_core.py -q`
  - `py -3 -m pytest tests/unit/test_phase12_context_policy.py -q`
  - `py -3 -m pytest tests/unit/test_phase12_context_executor_integration.py -q`
- 网页功能检查计划:
  - check `http://127.0.0.1:8501/_stcore/health`
  - open home / prediction ranking
  - open/render AI Agent
  - open/render AI paper trading
  - open/render system monitor

## Current State Summary

The current project has a useful but incomplete communication foundation:

- `agent/agent_protocol.py` already defines a minimal `AgentMessage` with `message_id`, `sender`, `receiver`, `payload`, and `summary`, plus `AgentOutput` and `timeline_entry`.
- Specialist agents return `AgentOutput`, but pass it by direct function return and dict fields such as `market_output`, `portfolio_output`, and `orchestration`, not through a message bus.
- `agent/executor.py` is the main communication hub. It builds `route_context`, creates Phase 12 `ContextBundle`, calls router/planner/tool paths, records runtime steps, and returns a large dict to UI.
- `agent/tool_engine.py` normalizes tool outputs into `UnifiedToolResult`, saves artifacts, and updates `ContextBundle`.
- `agent/write_gateway.py` remains the only confirmed write execution entry and forwards `confirmation_token` only to protected commit tools.
- UI pages render redacted result dicts with local redaction helpers, but there is no message-level policy or message store yet.

## Communication Audit Table

| communication_source | file | function/class | sender | receiver | payload_type | payload_fields | contains_context | contains_artifact_ref | contains_tool_result | contains_approval | contains_secret_risk | used_by_llm | used_by_ui | problem | planned_message_type | migration_phase |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| user request | `app/pages/ai_agent.py` | `_run_agent` | Streamlit UI/user | `agent.executor.run_agent_request` | function args | `query`, `user_id`, `output_dir`, `db_path`, `default_topk`, `session_id` | no | no | no | no | yes: `db_path`/local path args are internal | indirectly | yes | direct args, no envelope, UI can pass internal paths | `USER_REQUEST` | D |
| executor request entry | `agent/executor.py` | `run_agent_request` | UI/service | runtime/planner/tools | dict/local vars | `query`, `user_id`, `session_id`, `runtime`, `context_payload`, `context_warnings` | yes | later | later | later | yes: local paths and runtime internals | yes, via sanitized planner context | yes, final result | central dict accumulation, no message identity per transition | `USER_REQUEST`, `CONTEXT_CREATED` | D |
| route_context | `agent/executor.py` | `run_agent_request` | executor | `route_agent_query` / planner | dict | `user_id`, `session_id`, `default_top_k`, `run_id`, `runtime_policy`, `mcp`, `context_bundle`, `context_bundle_llm`, `agent_context` | yes | yes via context | no | yes via context | yes: `run_id`, MCP local config must stay sanitized | yes | no direct | no policy boundary between planner-visible and tool-only fields except manual construction | `CONTEXT_CREATED`, `GOAL_PARSED`, `TASK_PLANNED` | D |
| ContextBundle | `agent/context/context_types.py` | `ContextBundle` | ContextManager | executor/tool/context store | dataclass/dict | `context_id`, `user_context`, `conversation_context`, `task_context`, `tool_context`, `portfolio_context`, `evidence_context`, `artifact_context`, `approval_context`, `runtime_context` | yes | yes | yes summary | yes summary | medium: approval/artifact/runtime metadata need target policy | yes through `build_llm_context` | yes through summaries | context is structured but not represented as message refs | `CONTEXT_CREATED` | D |
| ToolContext | `agent/context/context_builder.py` | `ContextManager.build_tool_context` | ContextManager | ToolExecutor/tool handler | sanitized dict | permission-scoped context bundle view | yes | yes | yes summary | yes summary | low/medium: tool-only context can include local refs | no | no direct | no message refs or delivery audit | `CONTEXT_CREATED` | D |
| ToolExecutor input | `agent/tool_engine.py` | `ToolExecutor.execute` | executor/UI/write gateway | tool definition handler | function args + dict | `tool_name`, `arguments`, `context`, `context_bundle`, `tool_context`, `agent_type`, `approval_granted` | yes | yes | no | yes if approval tool | high if `confirmation_token` enters args for commit tools; must never be visible message | no | no direct | protected args are not separated into secret tool-only message fields | `TOOL_CALL_REQUESTED` | D |
| UnifiedToolResult | `agent/tool_engine.py` | `UnifiedToolResult`, `ToolExecutor.execute` | ToolExecutor | executor/UI/context/artifact store | dataclass/dict | `success`, `tool_name`, `message`, `data`, `warnings`, `errors`, `metadata`, `artifact_id`, timings | yes in metadata | yes | yes | possibly | medium: metadata can contain artifact path or internal error text | sometimes after aggregation | yes, redacted | result format exists but not message typed; metadata visibility is ad hoc | `TOOL_RESULT_RECEIVED`, `ARTIFACT_CREATED`, `ERROR_RAISED`, `WARNING_RAISED` | D |
| legacy ToolResult | `agent/tools/tool_schemas.py` and legacy callers | `ToolResult` | legacy tool path | executor/UI/adapters | dataclass/dict | `success`, `message`, `data`, `warnings`, `errors`, `requires_confirmation`, `tool_name` | sometimes | no standard | yes | yes | medium: legacy dicts may carry pending plan fields | sometimes | yes | older format coexists with UnifiedToolResult | `TOOL_RESULT_RECEIVED` | D/F |
| artifact refs | `agent/artifacts.py` | `save_tool_result_artifact`, `ArtifactStore.save` | ToolExecutor | ArtifactStore/ContextManager/UI summary | dict | `artifact_id`, `artifact_type`, `tool_name`, `created_at`, metadata | no | yes | yes by ref | no | high if raw path leaks; ContextStore later uses safe ref | no | yes via redacted result/context | artifact refs are metadata, not first-class messages | `ARTIFACT_CREATED` | C/D |
| approval pending plan | `agent/session/confirmation_manager.py` | `create_confirmation_plan` | preview/write-proposal tool | pending plan store/UI | dict | `plan_id`, `intent`, `operation_type`, `before_state_summary`, `proposed_changes`, `after_state_preview`, `confirmation_token`, `confirmation_token_hash`, status, expiry | business state | no | no | yes | high: raw token exists in stored plan and must not enter LLM/UI message | no | yes but redacted | approval payload contains secret and visible fields together | `APPROVAL_REQUESTED` | D |
| confirmation result | `agent/write_gateway.py` | `execute_confirmed_plan_v2` | UI/confirmation flow | protected commit tool | UnifiedToolResult | `plan_id`, `confirmation_token`, `user_id`, `write_gateway` metadata, result data | yes in context | yes result artifact | yes | yes | high: token is accepted as tool-only secret | no | yes redacted | no message policy distinguishes token-bearing command from UI-visible approval result | `APPROVAL_RESULT_RECEIVED`, `TOOL_CALL_REQUESTED`, `TOOL_RESULT_RECEIVED` | D |
| runtime trace | `agent/runtime.py` | `AgentRuntimeRecorder` | executor | database/UI monitor | DB records/dicts | `agent_runs`, `agent_steps`, `agent_tool_calls`, metadata, status, timings | yes summary | yes source refs | yes summary | yes via plan ids | medium: stack/errors/internal metadata need sanitizer | no | yes via AI Agent/system monitor | trace tables exist but are not message store | `OBSERVATION_CREATED`, `ERROR_RAISED`, `WARNING_RAISED` | C/D |
| warnings/errors | `agent/executor.py`, `agent/orchestration/multi_task_executor.py`, tools | many result builders | tools/executor/observer | UI/runtime/planner aggregation | list[str]/dict | `warnings`, `errors`, `context_warnings`, `replan_audit`, `observations` | sometimes | sometimes | yes | sometimes | medium/high: raw exception text may include paths | sometimes in aggregation | yes | no common `ErrorMessage` schema or sanitization per audience | `ERROR_RAISED`, `WARNING_RAISED` | B/D |
| AI Agent page result rendering | `app/pages/ai_agent.py` | `_render_result_details`, `_redact_ui_payload`, `_persist_conversation_message` | executor result | Streamlit user/conversation store | dict | full `agent_result`, context summary, raw result expander | yes summary | yes redacted | yes | yes redacted | medium: relies on recursive page redactor | no | yes | UI reads broad result dict rather than UI-safe messages | `FINAL_REPORT`, `REPORT_DRAFTED` | E |
| AI Paper Trading result rendering | `app/pages/ai_paper_trading.py` | `_render_write_proposal_confirmation`, `_redact_paper_ui_payload` | ToolExecutor/WriteGateway | Streamlit user | dict/result | pending plan, commit result, paper backfill/cash flow results | yes | maybe | yes | yes | medium/high: pending plan contains token unless redacted | no | yes | page-level redactor exists, no shared MessagePolicy | `APPROVAL_REQUESTED`, `APPROVAL_RESULT_RECEIVED` | E |
| multi_task_executor result passing | `agent/orchestration/multi_task_executor.py` | `execute_multi_intent_plan_async` | planner/tasks/tools | result aggregator/executor | dict | `task_results`, `tool_calls`, `execution_batches`, `observations`, `replan_audit`, `runtime_limits` | via execution_context | no direct | yes | no writes allowed in replan | medium: task result data can be large/internal | yes after aggregation | yes | task DAG exists as dicts, no message envelope per task | `TASK_PLANNED`, `TOOL_CALL_REQUESTED`, `TOOL_RESULT_RECEIVED`, `OBSERVATION_CREATED` | D |
| specialist agent result passing | `agent/specialists/*.py` | `MarketIntelligenceAgent.run`, `PortfolioAnalysisAgent.run`, `RiskOperationAgent.run`, `ReportingAgent.run` | specialist agent | supervisor/reporting/next specialist | `AgentOutput` + orchestration dict | `role`, `message_id`, `status`, `evidence`, `analysis`, `proposal`, `risks`, `next_actions`, `sources`, `tool_calls`, `handoff_from`, `handoff_to` | yes through args/context | yes sources | yes tool calls | risk agent proposal | medium: proposal must avoid secret fields | no direct except report generation | yes through final dict | closest existing protocol, but not persisted/routed as AgentMessage | `REPORT_DRAFTED`, `HANDOFF_REQUESTED` reserved | D/F |
| goal / task planning | `agent/router.py`, `agent/goal_planning.py`, `agent/intent_decomposition/` | `route_agent_query`, `attach_goal_planning_to_decomposition` | router/planner | executor/multi_task_executor | decomposition dict | `intent`, `parameters`, `tasks`, `dependencies`, `supervisor_decision`, diagnostics | yes via route_context | no | no | write flags | low/medium: diagnostics may contain planner internals | yes | yes diagnostics | goal/task plan not emitted as durable message | `GOAL_PARSED`, `TASK_PLANNED` | D |

## Target Message Protocol Design

### AgentMessage

Target fields:

- `message_id`: stable unique id.
- `conversation_id`: conversation/session id.
- `run_id`: runtime run id.
- `task_id`: current task id.
- `parent_task_id`: dependency or parent task id.
- `sender`: logical sender, such as `user`, `supervisor`, `tool_executor`, `write_gateway`.
- `receiver`: logical receiver, such as `planner`, `market_intelligence`, `ui`, `message_store`.
- `message_type`: enum value.
- `status`: lifecycle status.
- `priority`: routing priority.
- `created_at`: ISO timestamp.
- `payload`: sanitized payload for its target audience.
- `payload_schema`: schema/version name, for example `tool_result.v1`.
- `context_refs`: list of context ids or safe context summaries.
- `artifact_refs`: safe artifact ids/types only, no raw local path.
- `approval_refs`: safe approval ids/plan ids/hash/status only, no token.
- `tool_call_refs`: safe tool call ids/names/status.
- `source_refs`: news/source refs.
- `error`: structured sanitized error object.
- `warnings`: sanitized warning list.
- `metadata`: non-sensitive routing/debug metadata.

### MessageEnvelope

Envelope fields:

- `message`: `AgentMessage`
- `delivery_id`
- `visibility`: `llm`, `ui`, `tool`, `audit`, `internal`
- `policy_applied`
- `sanitized_at`
- `delivery_status`
- `retry_count`
- `route`

### MessageType

Required Phase 13 enum values:

- `USER_REQUEST`
- `CONTEXT_CREATED`
- `GOAL_PARSED`
- `TASK_PLANNED`
- `TOOL_CALL_REQUESTED`
- `TOOL_RESULT_RECEIVED`
- `OBSERVATION_CREATED`
- `APPROVAL_REQUESTED`
- `APPROVAL_RESULT_RECEIVED`
- `ARTIFACT_CREATED`
- `ERROR_RAISED`
- `WARNING_RAISED`
- `REPORT_DRAFTED`
- `FINAL_REPORT`
- `HANDOFF_REQUESTED`
- `REFLECTION_REQUESTED`
- `REFLECTION_RESULT`

`HANDOFF_*` and `REFLECTION_*` are reserved protocol values only in this phase. They must not implement full handoff/reflection behavior yet.

### MessageStatus

Suggested values:

- `created`
- `queued`
- `delivered`
- `observed`
- `succeeded`
- `failed`
- `blocked`
- `redacted`
- `expired`

### MessagePriority

Suggested values:

- `low`
- `normal`
- `high`
- `critical`

### MessageVisibility

Suggested values:

- `internal`
- `audit`
- `tool`
- `llm`
- `ui`

Rules:

- `llm` cannot see confirmation tokens, API keys, DB paths, local paths, stack traces, raw tool args for protected writes, or raw artifact paths.
- `ui` cannot see confirmation tokens, API keys, DB paths, local paths, stack traces, or raw artifact paths.
- `tool` may receive protected write secrets only through WriteGateway and ToolExecutor, not through planner/reporting messages.
- `audit` may store sanitized refs and hashes; raw secret fields should be excluded or hashed.

### MessagePolicy

The policy should define:

- field visibility by target audience;
- sensitive key names, including `confirmation_token`, `confirmation_token_hash`, `api_key`, `token`, `db_path`, `path`, `file_path`, `traceback`, `stack`, `password`;
- max payload chars by message type and audience;
- artifact-ref-only rules for large tool results;
- approval-ref-only rules for pending plans;
- tool-only secret passing for protected commits;
- failure handling when sanitization detects unapproved secret fields.

### MessageSanitizer

The sanitizer should produce deterministic outputs:

- `sanitize_for_llm(message)`
- `sanitize_for_ui(message)`
- `sanitize_for_tool(message)`
- `sanitize_for_audit(message)`
- `redact_payload(value, visibility)`

It should reuse Phase 12 `ContextSanitizer` rules where possible, but not rewrite ContextManager.

### MessageStore

Target responsibilities:

- persist messages by `message_id`, `run_id`, `conversation_id`, `task_id`, `message_type`, `sender`, `receiver`, and `created_at`;
- store sanitized payload only;
- store refs to runtime/tool/artifact/approval records;
- support listing run messages for UI trace;
- not write business state.

Stage C should decide whether to add a new table or map onto existing runtime tables. Stage A only records the need.

### MessageBus

Target responsibilities:

- `publish(message, visibility=...)`
- `publish_event(...)` compatibility helper for existing dict paths
- sanitize with `MessagePolicy`
- persist through `MessageStore`
- return the stored/sanitized message envelope

The bus must be append-only for traceability and must not execute business writes.

### MessageRouter

Target responsibilities:

- map sender/receiver/type to visibility and destination;
- provide compatibility adapters for Executor, ToolExecutor, ContextManager, WriteGateway, and UI;
- reject direct write routing except through WriteGateway events.

## MessageBus Integration Points Design

| integration point | current code | target event | notes |
| --- | --- | --- | --- |
| user request received | `app/pages/ai_agent.py::_run_agent` and `agent/executor.py::run_agent_request` | `USER_REQUEST` | publish sanitized user query and ids; no DB path in LLM/UI payload |
| initial context created | `ContextManager.create_initial_context` called in `run_agent_request` | `CONTEXT_CREATED` | publish context id and minimal refs |
| route/planner result | `agent/router.py::route_agent_query` and decomposition diagnostics | `GOAL_PARSED`, `TASK_PLANNED` | publish intent/task/dependency summary |
| tool request | `_registered_tool` in `agent/executor.py`; `ToolExecutor.execute` | `TOOL_CALL_REQUESTED` | publish args summary, not raw protected args |
| tool result | `ToolExecutor.execute` returns `UnifiedToolResult` | `TOOL_RESULT_RECEIVED` | publish result summary and artifact ref |
| artifact saved | `agent/artifacts.py::save_tool_result_artifact` | `ARTIFACT_CREATED` | publish safe artifact ref only |
| observe/replan | `multi_task_executor._observe_task_results` and `replan_audit` | `OBSERVATION_CREATED` | publish deterministic observe summary |
| approval requested | `create_confirmation_plan` / preview tools | `APPROVAL_REQUESTED` | publish plan id/hash/status, no token |
| approval result | `execute_confirmed_plan_v2` | `APPROVAL_RESULT_RECEIVED` | publish accepted/rejected/committed summary, no token |
| final response | `run_agent_request` final dict and AI Agent UI render | `FINAL_REPORT` | publish answer and trace refs |

## Compatibility Notes

- Existing dict returns and `UnifiedToolResult.to_legacy_dict()` must remain available while AgentMessage is introduced.
- The existing minimal `agent.agent_protocol.AgentMessage` can be migrated rather than duplicated, but it lacks `message_type`, status, refs, visibility, and policy integration.
- `AgentOutput` is useful as a specialist payload schema and should be carried inside `REPORT_DRAFTED` or reserved `HANDOFF_REQUESTED` messages later.
- Existing runtime tables are trace tables, not a message store. MessageStore should reference them without replacing them.

## Sensitive Field Risks

Identified risks:

- `confirmation_token` exists in pending plans and WriteGateway tool args. It must remain tool-only and must not enter UI/LLM messages.
- API keys and Tushare token appear as password fields in the UI runtime DOM. They must not be included in page-check logs, message payloads, or screenshots.
- `db_path`, `output_dir`, artifact local paths, and stack traces can leak local machine details.
- `UnifiedToolResult.metadata.artifact_ref` and runtime metadata can contain internal ids or paths and must be sanitized by target visibility.
- UI pages currently rely on local redactors (`_redact_ui_payload`, `_redact_paper_ui_payload`), so Phase 13 should centralize this at MessagePolicy while keeping UI redactors as defense-in-depth.

## Test Commands And Results

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts`
  - result: passed
- `py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q`
  - result: passed, 7 tests, warnings only
- `py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q`
  - result: passed, 6 tests
- `py -3 -m pytest tests/unit/test_phase12_context_core.py -q`
  - result: passed, 2 tests
- `py -3 -m pytest tests/unit/test_phase12_context_policy.py -q`
  - result: passed, 4 tests
- `py -3 -m pytest tests/unit/test_phase12_context_executor_integration.py -q`
  - result: passed, 2 tests, warnings only

## Web Check

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = health check + browser Playwright + Streamlit AppTest page-render check

WEB_CHECK_PAGES = [
  "http://127.0.0.1:8501/_stcore/health",
  "首页 / 预测排名",
  "AI Agent",
  "AI 模拟盘",
  "系统监控"
]

WEB_CHECK_RESULT = pass

WEB_CHECK_ERRORS = [
  "In-app browser DOM snapshot/evaluate timed out twice after initial successful checks; completed page coverage with local Playwright for home and Streamlit AppTest for all four pages.",
  "Headless browser DOM did not expose the top-level st.radio navigation text, while Streamlit AppTest confirmed radio options and page switching.",
  "System monitor emitted a Streamlit dataframe Arrow auto-fix warning for a mixed-type value column, but rendered with no Streamlit exception and no error component."
]

Observed:

- Health endpoint returned `ok`.
- Browser opened home page and found title/ranking content with no Traceback/Exception.
- Browser opened AI Agent before the browser connection reset and found `AI Agent 控制中心` and chat prompt content with no Traceback/Exception.
- Streamlit AppTest rendered and switched:
  - `首页 / 预测排名`: no exception, no error component.
  - `AI Agent`: no exception, no error component.
  - `AI 模拟盘`: no exception, no error component.
  - `系统监控`: no exception, no error component.

## Files Added Or Modified

- added `docs/phase13_a_communication_audit_report.md`

## Failed Items

- none blocking for Phase 13-A.

## Unfinished Items For Later Phases

- implement actual core models and sanitizer in Phase 13-B.
- implement MessageStore/MessageBus/MessageRouter in Phase 13-C.
- integrate Executor/ToolExecutor/WriteGateway/Context in Phase 13-D.
- add UI message trace display in Phase 13-E.
- add final coverage/regression report in Phase 13-F.

NEXT_STAGE_ALLOWED = true
