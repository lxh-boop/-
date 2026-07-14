# Phase 13-B Message Core Report

## Stage Goal

Phase 13-B adds the standalone communication core models and safety policy. This stage does not connect the new communication package to Executor, ToolExecutor, WriteGateway, ContextManager, or UI behavior.

## Added Files

- `agent/communication/__init__.py`
- `agent/communication/message_types.py`
- `agent/communication/message_policy.py`
- `agent/communication/message_sanitizer.py`
- `agent/communication/message_window.py`
- `tests/unit/test_phase13_message_core.py`
- `tests/unit/test_phase13_message_policy.py`
- `docs/phase13_b_message_core_report.md`

## Message Models

Implemented:

- `AgentMessage`
  - fields: `message_id`, `conversation_id`, `run_id`, `task_id`, `parent_task_id`, `sender`, `receiver`, `message_type`, `status`, `priority`, `created_at`, `payload`, `payload_schema`, `context_refs`, `artifact_refs`, `approval_refs`, `tool_call_refs`, `source_refs`, `error`, `warnings`, `metadata`.
  - supports `to_dict()` and `from_dict()`.
- `MessageEnvelope`
  - fields: `envelope_id`, `message`, `route`, `visibility`, `delivery_status`, `retry_count`, `created_at`, `delivered_at`, `trace_id`.
- `MessageSummary`
  - compact summary object for old/trimmed messages.

## Message Types

Implemented `MessageType` values:

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

Also implemented:

- `MessageStatus`: `CREATED`, `QUEUED`, `DELIVERED`, `CONSUMED`, `FAILED`, `SKIPPED`, `EXPIRED`
- `MessagePriority`: `LOW`, `NORMAL`, `HIGH`, `CRITICAL`
- `MessageVisibility`: `LLM_VISIBLE`, `TOOL_ONLY`, `SYSTEM_ONLY`, `UI_VISIBLE`, `AUDIT_ONLY`, `SECRET`

## MessagePolicy Rules

Implemented methods:

- `classify_field()`
- `classify_message()`
- `can_deliver()`
- `can_show_to_llm()`
- `can_show_to_ui()`
- `requires_redaction()`

Core rules:

- `confirmation_token`, `confirmation_token_hash`, API keys, passwords, token/secret fields -> `SECRET`
- `db_path`, `database_path`, local paths, output paths -> `SYSTEM_ONLY`
- stack traces / tracebacks -> `AUDIT_ONLY`
- `raw_positions`, `raw_evidence`, `full_payload`, `raw_payload`, `full_result` -> `TOOL_ONLY`
- summaries, refs, ids, `token_present`, `plan_hash` -> `LLM_VISIBLE`

## MessageSanitizer Results

Implemented methods:

- `sanitize_for_llm()`
- `sanitize_for_ui()`
- `sanitize_for_tool()`
- `sanitize_for_audit()`

Verified behavior:

- LLM payload does not contain confirmation tokens, API keys, DB paths, local paths, or stack traces.
- UI payload does not contain confirmation tokens, API keys, DB paths, local paths, or stack traces.
- Tool payload can retain `TOOL_ONLY` fields, but read-scope tool context does not receive system paths or secrets.
- Audit payload redacts secrets with `***` while retaining audit-visible information.

## MessageWindow Rules

Implemented:

- `trim_messages_to_budget()`
- `summarize_old_messages()`
- `keep_required_messages()`
- `estimate_message_size()`

Rules:

- Keep `USER_REQUEST`.
- Keep `FINAL_REPORT`.
- Summarize old messages when budget is exceeded.
- Convert `APPROVAL_REQUESTED` to approval summary fields only.
- Convert `TOOL_RESULT_RECEIVED` to summary + artifact refs, avoiding large raw payloads.

## Compatibility

- Existing `agent/agent_protocol.py` remains unchanged.
- No old dict/result interface was removed.
- No main execution path imports the new communication package yet.
- `HANDOFF_REQUESTED` and reflection message types are only reserved protocol values.

## Test Commands And Results

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts`
  - result: passed
- `py -3 -m pytest tests/unit/test_phase13_message_core.py -q`
  - result: passed, 3 tests
- `py -3 -m pytest tests/unit/test_phase13_message_policy.py -q`
  - result: passed, 3 tests
- `py -3 -m pytest tests/unit/test_phase12_context_policy.py -q`
  - result: passed, 4 tests
- `py -3 -m pytest tests/unit/test_phase12_context_core.py -q`
  - result: passed, 2 tests
- `py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q`
  - result: passed, 7 tests, warnings only

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
- Browser Playwright opened home page and found ranking content with no Traceback/Exception.
- Streamlit AppTest switched all four target pages.
- All four pages had `exceptions = 0` and `error_count = 0`.

## Failed Items

- none blocking for Phase 13-B.

## Unfinished Items For Later Phases

- Stage C still needs MessageStore, MessageBus, and MessageRouter.
- Stage D still needs non-breaking integration with Executor, ToolExecutor, WriteGateway, and Context.
- Stage E still needs UI-safe message trace display.

NEXT_STAGE_ALLOWED = true
