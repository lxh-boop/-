# Phase 13-D Message Integration Report

## Stage Goal

Phase 13-D connects the Phase 13 communication system to the main execution path in a backward-compatible way. Existing dict/result APIs, ToolExecutor permissions, WriteGateway approval/revalidate/commit, and ContextManager behavior remain unchanged.

## Added / Modified Files

- added `agent/communication/integration.py`
- modified `agent/communication/__init__.py`
- modified `agent/executor.py`
- modified `agent/tool_engine.py`
- modified `agent/write_gateway.py`
- modified `agent/session/confirmation_manager.py`
- added `tests/unit/test_phase13_message_executor_integration.py`
- added `tests/unit/test_phase13_message_tool_executor_integration.py`
- added `tests/unit/test_phase13_message_write_gateway_integration.py`
- added `docs/phase13_d_message_integration_report.md`

## Executor Integration Points

`agent/executor.py::run_agent_request` now publishes:

- `USER_REQUEST`
- `CONTEXT_CREATED`
- `GOAL_PARSED`
- `TASK_PLANNED`
- `FINAL_REPORT`

Payload rules:

- request payload contains query summary and top-k/language only.
- context payload contains `context_id` and locale only.
- task plan payload contains task ids, intents, dependencies, and capability status.
- final report payload contains answer summary, runtime status, intent, and tool name.
- full `ContextBundle` is not placed in message payload.
- context refs are generated with `context_ref_from_bundle()`.

Compatibility:

- `run_agent_request()` return shape is unchanged.
- existing runtime checkpoint and context snapshot behavior is unchanged.

## ToolExecutor Integration Points

`agent/tool_engine.py::ToolExecutor.execute` now publishes:

- `TOOL_CALL_REQUESTED`
- `TOOL_RESULT_RECEIVED`
- `ARTIFACT_CREATED`
- `APPROVAL_REQUESTED` when a successful tool result contains `plan_id`
- `ERROR_RAISED` for validation/permission/runtime tool failures

Payload rules:

- tool call payload stores tool name, canonical tool name, operation type, agent type, approval flag, and safe argument key summary.
- sensitive argument names such as `confirmation_token`, API key, password, token, and secret are converted to `secret_arg`.
- argument values are never written to messages.
- tool result payload stores success/message/tool/artifact/plan summary.
- artifact messages store safe artifact refs only.

Compatibility:

- `UnifiedToolResult` structure is unchanged.
- old calls without `output_dir` remain effectively no-op for message publishing.
- ToolExecutor permission checks are unchanged.

## WriteGateway Integration Points

`agent/write_gateway.py::execute_confirmed_plan_v2` now publishes:

- `APPROVAL_RESULT_RECEIVED`

`agent/session/confirmation_manager.py::create_confirmation_plan` now publishes:

- `APPROVAL_REQUESTED`

Additional run-scoped `APPROVAL_REQUESTED` is also published by ToolExecutor when preview/proposal tools return a `plan_id`, so the approval request can be traced against the current `run_id`.

Payload rules:

- approval request/result payloads include only plan id, plan hash, status, token_present, success/message, and summary.
- raw `confirmation_token` value is never written.
- raw `confirmation_token` field name is not emitted in safe argument key summaries.
- MessageBus does not perform commit. Commit remains inside `execute_confirmed_plan_v2`.

## ContextManager Integration Points

Context integration is reference-only:

- `context_id`
- `run_id`
- `conversation_id`
- `task_id`

No complete `ContextBundle` is placed in message payload.

## Artifact Integration Points

ToolExecutor messages use `artifact_refs_from_result()`:

- `artifact_id`
- `artifact_type`
- `tool_name`
- `produced_outputs`

Raw artifact paths are not emitted.

## Compatibility With Legacy Interfaces

- Existing `run_agent_request()` dict response remains unchanged.
- Existing `execute_tool()` / `execute_tool_legacy_dict()` behavior remains unchanged.
- Existing `execute_confirmed_plan_v2()` behavior remains unchanged.
- Existing P0 approval/revalidate/commit tests continue to pass.
- Existing proposal gateway tests continue to pass.

## Message Types Actually Produced

Validated by tests and AI Agent page checks:

- `USER_REQUEST`
- `CONTEXT_CREATED`
- `GOAL_PARSED`
- `TASK_PLANNED`
- `TOOL_CALL_REQUESTED`
- `TOOL_RESULT_RECEIVED`
- `ARTIFACT_CREATED`
- `APPROVAL_REQUESTED`
- `APPROVAL_RESULT_RECEIVED`
- `ERROR_RAISED`
- `FINAL_REPORT`

## Test Commands And Results

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts`
  - result: passed
- `py -3 -m pytest tests/unit/test_phase13_message_executor_integration.py -q`
  - result: passed, 1 test
- `py -3 -m pytest tests/unit/test_phase13_message_tool_executor_integration.py -q`
  - result: passed, 2 tests
- `py -3 -m pytest tests/unit/test_phase13_message_write_gateway_integration.py -q`
  - result: passed, 1 test
- `py -3 -m pytest tests/unit/test_phase13_message_store_bus.py -q`
  - result: passed, 3 tests
- `py -3 -m pytest tests/unit/test_phase13_message_policy.py -q`
  - result: passed, 3 tests
- `py -3 -m pytest tests/unit/test_phase12_context_executor_integration.py -q`
  - result: passed, 2 tests, warnings only
- `py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q`
  - result: passed, 6 tests
- `py -3 -m pytest tests/unit/test_agent_write_requires_confirmation.py -q`
  - result: passed, 1 test
- `py -3 -m pytest tests/unit/test_agent_action_proposal_gateway.py -q`
  - result: passed, 3 tests
- final combined D integration rerun:
  - `py -3 -m pytest tests/unit/test_phase13_message_executor_integration.py tests/unit/test_phase13_message_tool_executor_integration.py tests/unit/test_phase13_message_write_gateway_integration.py -q`
  - result: passed, 4 tests

## Real Web Function Check

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = health check + browser Playwright home-page render + Streamlit AppTest page switching and AI Agent chat input

WEB_CHECK_PAGES = [
  "http://127.0.0.1:8501/_stcore/health",
  "首页 / 预测排名",
  "AI Agent",
  "AI 模拟盘",
  "系统监控"
]

WEB_CHECK_RESULT = pass

WEB_CHECK_ERRORS = [
  "System monitor emitted the existing Streamlit dataframe Arrow auto-fix warning for a mixed-type value column, but rendered with no Streamlit exception and no error component."
]

Page checks:

- Health endpoint returned `ok`.
- Browser Playwright opened the home page and found ranking content with no Traceback/Exception.
- Streamlit AppTest switched all four target pages.
- All four pages had `exceptions = 0` and `error_count = 0`.

AI Agent actual inputs:

| input | expected | actual_summary | message_created | message_types_seen | secret_visible | traceback_error | result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 查看我的当前持仓 | return holdings or safe explanation, no error | page responded with answer signal | true | `USER_REQUEST`, `CONTEXT_CREATED`, `GOAL_PARSED`, `TASK_PLANNED`, `TOOL_CALL_REQUESTED`, `TOOL_RESULT_RECEIVED`, `ARTIFACT_CREATED`, `FINAL_REPORT` | false | false | pass |
| 分析当前组合风险 | return risk analysis or safe explanation, no error | page responded with answer signal | true | `USER_REQUEST`, `CONTEXT_CREATED`, `GOAL_PARSED`, `TASK_PLANNED`, `TOOL_CALL_REQUESTED`, `TOOL_RESULT_RECEIVED`, `ARTIFACT_CREATED`, `FINAL_REPORT` | false | false | pass |
| 给我一个调仓建议 | return recommendation/proposal/safe explanation, no direct commit | page responded with answer signal | true | `USER_REQUEST`, `CONTEXT_CREATED`, `GOAL_PARSED`, `TASK_PLANNED`, `TOOL_CALL_REQUESTED`, `TOOL_RESULT_RECEIVED`, `ARTIFACT_CREATED`, `FINAL_REPORT` | false | false | pass |
| 查看系统状态 | return system status or safe explanation, no error | page responded with answer signal | true | `USER_REQUEST`, `CONTEXT_CREATED`, `GOAL_PARSED`, `TASK_PLANNED`, `TOOL_CALL_REQUESTED`, `TOOL_RESULT_RECEIVED`, `ARTIFACT_CREATED`, `FINAL_REPORT` | false | false | pass |

## Failed Items

- none blocking for Phase 13-D.

## Unfinished Items For Later Phases

- Stage E still needs UI message trace display.
- Stage F still needs final coverage/regression delivery report.

NEXT_STAGE_ALLOWED = true
