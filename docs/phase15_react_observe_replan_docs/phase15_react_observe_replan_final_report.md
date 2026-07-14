# Phase 15 ReAct Observe / Replan Final Report

## Phase Reports

| Stage | Report | Result |
| --- | --- | --- |
| A | `docs/phase15_a_react_loading_audit_report.md` | NEXT_STAGE_ALLOWED = true |
| B | `docs/phase15_b_observation_core_report.md` | NEXT_STAGE_ALLOWED = true |
| C | `docs/phase15_c_observe_store_replan_report.md` | NEXT_STAGE_ALLOWED = true |
| D | `docs/phase15_d_react_runtime_integration_report.md` | NEXT_STAGE_ALLOWED = true |
| E | `docs/phase15_e_ai_agent_ui_loading_report.md` | NEXT_STAGE_ALLOWED = true |
| F | `docs/phase15_react_observe_replan_final_report.md` | NEXT_STAGE_ALLOWED = true |

## Added React Modules

- `agent/react/observation_types.py`
- `agent/react/observe_policy.py`
- `agent/react/observe_sanitizer.py`
- `agent/react/observation_window.py`
- `agent/react/observe_store.py`
- `agent/react/react_trace.py`
- `agent/react/replan_types.py`
- `agent/react/replan_policy.py`
- `agent/react/integration.py`
- `agent/react/react_context_bridge.py`

## ObservationEvent

Core fields:

- `observation_id`
- `conversation_id`
- `run_id`
- `task_id`
- `parent_task_id`
- `source_message_id`
- `source_tool_name`
- `observation_type`
- `status`
- `severity`
- `created_at`
- `summary`
- `detail`
- `context_refs`
- `artifact_refs`
- `message_refs`
- `memory_refs`
- `approval_refs`
- `tool_call_refs`
- `source_refs`
- `error`
- `warnings`
- `metadata`

ObservationType list:

- `TOOL_SUCCESS`
- `TOOL_EMPTY_RESULT`
- `TOOL_ERROR`
- `TOOL_PERMISSION_BLOCKED`
- `CONTEXT_INSUFFICIENT`
- `EVIDENCE_INSUFFICIENT`
- `MEMORY_HIT`
- `MEMORY_EMPTY`
- `APPROVAL_REQUIRED`
- `APPROVAL_DENIED`
- `TASK_PARTIAL_SUCCESS`
- `TASK_FAILED`
- `REPORT_READY`
- `USER_CLARIFICATION_NEEDED`
- `SYSTEM_WARNING`

## Replan Types

ReplanReason list:

- `missing_required_context`
- `missing_required_parameter`
- `tool_error_recoverable`
- `tool_error_blocking`
- `tool_result_empty`
- `evidence_insufficient`
- `memory_insufficient`
- `permission_blocked`
- `approval_required`
- `approval_denied`
- `user_goal_changed`
- `task_dependency_failed`
- `max_context_budget_exceeded`
- `max_replan_limit_reached`

ReplanScope list:

- `NO_REPLAN`
- `CURRENT_TASK`
- `DEPENDENT_TASKS`
- `PLAN_SUMMARY_ONLY`
- `ASK_USER_CLARIFICATION`
- `BLOCK_AND_REPORT`

ReplanDecisionStatus list:

- `REQUESTED`
- `SKIPPED`
- `APPLIED`
- `BLOCKED`
- `WAIT_APPROVAL`

ReplanLimiter:

- `max_run_replans = 2`
- `max_task_replans = 1`
- `max_same_reason = 1`

## Integration Points

- ToolExecutor integration: `agent/tool_engine.py` records tool success, empty result, permission block, approval-required, and exception observations through `record_tool_observation`.
- Executor integration: `agent/executor.py` records final task/report observations and evaluates replan decisions through `record_executor_result_observation`.
- Context integration: `agent/context/context_types.py` and `agent/context/context_policy.py` carry only observation/replan refs and safe ids into minimal context.
- MessageBus integration: `agent/communication/message_types.py` adds `OBSERVATION_CREATED`, `REPLAN_REQUESTED`, `REPLAN_SKIPPED`, `REPLAN_APPLIED`, and `REPLAN_BLOCKED`.
- Store integration: `ObserveStore` writes sanitized jsonl observation records under `outputs/react_logs/<user_id>/<run_id>.jsonl`.
- UI integration: `app/pages/ai_agent.py` shows safe captions and lazy details; `app/pages/system_monitor.py` shows ReAct health counters.

## Write And Memory Boundaries

- WriteGateway remains the only confirmed write execution boundary.
- Replan never commits portfolio or strategy state directly.
- Approval-required observations produce plan/replan messages only; execution still requires user confirmation and revalidation.
- Memory tools remain read-only; UI memory view loads only safe summaries and small sanitized pages.
- MCP write tools remain blocked by the existing tool policy.

## Loading Optimization

- AI Agent default visible message window: `10`.
- Chat history page size: `10`.
- Load-earlier step: `10`.
- Max message window: `100`.
- Long chat test: after 12 submitted messages, default visible messages were `10`; after clicking load earlier, visible messages increased to `20`.
- Context, Message Trace, ReAct trace, Memory records, and tool/result details are lazy-loaded behind checkboxes or collapsed detail sections.
- Memory default safe page size: `5`.

## Safety Results

Final target counters:

- `secret_exposure_count = 0`
- `confirmation_token_observation_exposure = 0`
- `confirmation_token_ui_exposure = 0`
- `raw_path_observation_exposure = 0`
- `raw_stack_ui_exposure = 0`
- `raw_payload_ui_exposure = 0`

Verified by:

- ObserveSanitizer, MessageSanitizer, ContextSanitizer, MemorySanitizer policy tests.
- ReAct UI safe trace tests.
- Memory safe page tests.
- Web scripts checking absence of `confirmation_token`, `agent_quant.db`, `raw_tool_payload`, and internal traceback markers.

## Tests

```powershell
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
```

Result: PASS.

```powershell
$patterns = @('test_phase11_*.py','test_phase12_*.py','test_phase13_*.py','test_phase14_*.py','test_phase15_*.py')
$files = foreach ($p in $patterns) { Get-ChildItem -Path tests\unit -Filter $p | ForEach-Object { $_.FullName } }
$files += @((Resolve-Path tests\unit\test_agent_write_requires_confirmation.py).Path, (Resolve-Path tests\unit\test_agent_action_proposal_gateway.py).Path, (Resolve-Path tests\unit\test_multi_agent_phase3_human_approval.py).Path)
py -3 -m pytest $files -q
```

Result: PASS, `163 passed`, `30 warnings`.

```powershell
py -3 scripts\check_phase15_react_loading_web.py
```

Result: PASS.

```powershell
py -3 scripts\check_phase13_communication_web.py
```

Result: PASS.

## Web Regression

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = Streamlit AppTest, local health endpoint, and in-app browser page switching/read-only inspection.

WEB_CHECK_PAGES =

- `http://127.0.0.1:8501/_stcore/health`
- Home / prediction ranking
- AI Agent
- AI paper trading
- System monitor

WEB_CHECK_RESULT =

- Health endpoint returned `ok`.
- Home, AI Agent, AI Paper Trading, and System Monitor rendered with 0 Streamlit exceptions and 0 AppTest errors.
- Required AI Agent prompts were exercised in the long-chat AppTest flow:
  - `查看我的当前持仓`
  - `分析当前组合风险`
  - `给我一个调仓建议`
  - `查看最新报告`
  - `查看系统状态`
  - `我上次为什么建议调仓？`
- Long chat windowing passed: 10 visible before load-earlier, 20 visible after load-earlier.
- ReAct trace caption and Memory safe summary were visible in the UI test.
- Browser switching verified Home, AI Agent, AI Paper Trading, and System Monitor page markers with no visible Traceback or sensitive-field markers.

WEB_CHECK_ERRORS =

- Browser `domSnapshot()` was unavailable for this Streamlit page due to browser-plugin `incrementalAriaSnapshot` incompatibility, so the browser check used read-only page text and targeted label clicks.
- Browser runtime printed unrelated Statsig network timeout logs from the host environment; local app checks were unaffected.

## Final Statistics

- `observation_types_defined = 15`
- `observations_emitted_in_agent_flow = yes`
- `executor_observe_coverage = final task/report result`
- `tool_executor_observe_coverage = success / empty / error / permission / approval-required`
- `replan_policy_coverage = success skip / empty requested / failure requested / approval wait / permission blocked / limiter`
- `replan_limit_config = run 2, task 1, same reason 1`
- `message_types_added = 5`
- `messages_emitted_in_react_flow = OBSERVATION_CREATED + REPLAN_*`
- `chat_default_visible_message_count = 10`
- `chat_history_page_size = 10`
- `memory_default_visible_record_count = 5`
- `memory_context_top_k = existing MemoryManager default path retained`
- `legacy_dict_compat_entries = ObservationEvent.from_dict, ReplanDecision.from_dict, sanitizer dict input, ToolExecutor context dict input`

## Compatibility Retained

- Existing `UnifiedToolResult` return shape is unchanged.
- Existing tool registry and v2 executor are retained.
- Existing ContextManager and MessageBus APIs are retained.
- Existing MemoryManager store/retriever APIs are retained.
- Existing approval and pending-plan UI entry points remain compatible.
- Legacy dict inputs for observations, replan decisions, messages, and context refs are supported.

## Explicitly Not Implemented

- Full Reflection Critic.
- Full Multi-Agent Handoff.
- Direct Replan execution or auto-commit.
- Any MCP write path.
- Any rewrite of the tool, context, communication, or memory systems.

## Remaining Issues

- System Monitor ReAct health depends on available `outputs/react_logs` entries for the selected user; a fresh default user can legitimately show zero observations.
- Browser plugin DOM snapshot incompatibility remains outside the project code; AppTest plus read-only browser inspection covers the acceptance check.

## Next Stage Recommendation

Phase 16 can build a bounded Reflection Critic on top of the existing Observation, Message, Context, and Memory refs. It should remain advisory only at first and must not be allowed to bypass WriteGateway, approval, revalidation, or deterministic risk rules.

NEXT_STAGE_ALLOWED = true
