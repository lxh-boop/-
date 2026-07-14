# Phase 13-C Message Store / Bus / Router Report

## Stage Goal

Phase 13-C adds lightweight local communication infrastructure: MessageStore, MessageBus, MessageRouter, and MessageTrace. This stage does not connect the infrastructure into the main business execution chain.

## Added / Modified Files

- added `agent/communication/message_store.py`
- added `agent/communication/message_bus.py`
- added `agent/communication/message_router.py`
- added `agent/communication/message_trace.py`
- modified `agent/communication/__init__.py`
- modified `agent/communication/message_sanitizer.py`
- added `tests/unit/test_phase13_message_store_bus.py`
- added `tests/unit/test_phase13_message_router_trace.py`
- added `docs/phase13_c_message_store_bus_report.md`

## MessageStore Storage Method

Storage is local JSONL:

```text
outputs/message_logs/<user_id>/<run_id>.jsonl
```

No database schema was added.

Implemented methods:

- `save_message()`
- `load_message()`
- `list_messages_by_run()`
- `list_messages_by_conversation()`
- `list_messages_by_task()`
- `append_trace_event()`
- `expire_messages()`
- `build_trace()`

Safety:

- messages are sanitized with `sanitize_for_audit()` before writing.
- raw `confirmation_token` does not land on disk.
- raw API keys/secrets do not land on disk.
- raw DB/local paths are redacted from message audit logs.
- message id duplicate writes are skipped.

## MessageBus Capabilities

Implemented:

- `publish(message)`
- `publish_many(messages)`
- `subscribe(message_type, handler)`
- `dispatch(envelope)`
- `get_trace(run_id)`

Behavior:

- `publish()` writes the sanitized message through MessageStore and returns a routed envelope.
- `dispatch()` synchronously runs registered handlers.
- no subscribers means no-op dispatch.
- handler exceptions create an `ERROR_RAISED` AgentMessage and persist it.
- MessageBus does not execute business writes and does not bypass ToolExecutor or WriteGateway.

## MessageRouter Rules

Implemented:

- `route_message()`
- `route_to_executor()`
- `route_to_tool_executor()`
- `route_to_write_gateway()`
- `route_to_ui()`
- `route_to_audit()`

Current route map:

- `USER_REQUEST`, `GOAL_PARSED`, `TASK_PLANNED` -> `executor`
- `TOOL_CALL_REQUESTED` -> `tool_executor`
- `APPROVAL_REQUESTED`, `APPROVAL_RESULT_RECEIVED` -> `write_gateway`, `ui`, `audit`
- `REPORT_DRAFTED`, `FINAL_REPORT` -> `ui`, `audit`
- `ERROR_RAISED`, `WARNING_RAISED` -> `audit`, `ui`
- other messages -> `audit`

Router only decides destination. It does not call write tools or mutate business state.

## MessageTrace Structure

Implemented `MessageTrace` fields:

- `trace_id`
- `run_id`
- `message_ids`
- `parent_child_edges`
- `tool_call_edges`
- `artifact_edges`
- `approval_edges`
- `errors`
- `warnings`

Implemented helper:

- `build_message_trace(messages, trace_id="")`

Trace derives:

- parent-child task edges from `parent_task_id` and `task_id`
- tool edges from `tool_call_refs`
- artifact edges from `artifact_refs`
- approval edges from `approval_refs`
- errors/warnings from message fields

## Test Commands And Results

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts`
  - result: passed
- `py -3 -m pytest tests/unit/test_phase13_message_store_bus.py -q`
  - result: passed, 3 tests
- `py -3 -m pytest tests/unit/test_phase13_message_router_trace.py -q`
  - result: passed, 2 tests
- `py -3 -m pytest tests/unit/test_phase13_message_core.py -q`
  - result: passed, 3 tests
- `py -3 -m pytest tests/unit/test_phase13_message_policy.py -q`
  - result: passed, 3 tests
- `py -3 -m pytest tests/unit/test_phase12_context_executor_integration.py -q`
  - result: passed, 2 tests, warnings only

## Web Check

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = health check + browser Playwright home-page render + Streamlit AppTest page switching

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

Observed:

- Health endpoint returned `ok`.
- Browser Playwright opened the home page and found ranking content with no Traceback/Exception.
- Streamlit AppTest switched all four target pages.
- All four pages had `exceptions = 0` and `error_count = 0`.

## Failed Items

- none blocking for Phase 13-C.

## Unfinished Items For Later Phases

- Stage D still needs compatibility integration points in Executor, ToolExecutor, WriteGateway, and Context.
- Stage E still needs UI message trace display.
- Stage F still needs final coverage/regression delivery report.

NEXT_STAGE_ALLOWED = true
