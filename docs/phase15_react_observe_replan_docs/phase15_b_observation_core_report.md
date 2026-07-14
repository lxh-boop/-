# Phase 15-B Observation Core Report

## 阶段目标

建立 ReAct Observe 的核心观察模型、安全策略、脱敏器和窗口裁剪器；本阶段不接入 Executor/ToolExecutor 主链，不改变页面行为或业务结果。

## 修改前状态表

| 检查项 | 修改前 | 本阶段结果 |
|---|---|---|
| `agent/react/` | 不存在 | 已建立 |
| Observation 标准模型 | 只有 dict 型 observations 和 MessageType enum | 已新增 `ObservationEvent` |
| ObservePolicy | 不存在 | 已新增 |
| ObserveSanitizer | 不存在 | 已新增 |
| ObservationWindow | 不存在 | 已新增 |
| Executor/ToolExecutor 接入 | 不适用 | 未接入，按阶段要求保持不变 |

## 新增/修改文件

- Added `agent/react/__init__.py`
- Added `agent/react/observation_types.py`
- Added `agent/react/observe_policy.py`
- Added `agent/react/observe_sanitizer.py`
- Added `agent/react/observation_window.py`
- Added `tests/unit/test_phase15_observation_core.py`
- Added `tests/unit/test_phase15_observe_policy.py`

## Observation 模型

- `ObservationEvent`: observation_id, conversation_id, run_id, task_id, parent_task_id, source_message_id, source_tool_name, observation_type, status, severity, created_at, summary, detail, context_refs, artifact_refs, message_refs, memory_refs, approval_refs, tool_call_refs, source_refs, error, warnings, metadata.
- `ObservationSummary`: lightweight summary for old/large observations, with refs and `replan_required`.
- Both support `to_dict()` and enum-safe `from_dict()`.

## Observation 类型

Implemented:

- TOOL_SUCCESS
- TOOL_EMPTY_RESULT
- TOOL_ERROR
- TOOL_PERMISSION_BLOCKED
- CONTEXT_INSUFFICIENT
- EVIDENCE_INSUFFICIENT
- MEMORY_HIT
- MEMORY_EMPTY
- APPROVAL_REQUIRED
- APPROVAL_DENIED
- TASK_PARTIAL_SUCCESS
- TASK_FAILED
- REPORT_READY
- USER_CLARIFICATION_NEEDED
- SYSTEM_WARNING

## ObservePolicy 规则

- `confirmation_token`, `confirmation_token_hash`, API keys, Tushare token, password, secret -> `SECRET`
- `db_path`, `database_path`, local path, output dir -> `SYSTEM_ONLY`
- stack/traceback/internal stack -> `AUDIT_ONLY`
- `raw_positions`, `raw_evidence`, `raw_tool_payload`, full payload/result -> `TOOL_ONLY`
- summary, refs, status, token_present, error_type -> `LLM_VISIBLE`

Replan check returns true for:

- TOOL_EMPTY_RESULT
- TOOL_ERROR
- TOOL_PERMISSION_BLOCKED
- CONTEXT_INSUFFICIENT
- EVIDENCE_INSUFFICIENT
- APPROVAL_REQUIRED
- APPROVAL_DENIED
- TASK_PARTIAL_SUCCESS
- TASK_FAILED
- USER_CLARIFICATION_NEEDED

Replan check returns false for:

- TOOL_SUCCESS
- REPORT_READY
- MEMORY_HIT

## ObserveSanitizer 结果

- LLM/UI outputs remove secret fields, local paths, db paths, internal stack traces, and raw payload fields.
- Text-level redaction removes inline values such as `confirmation_token=...` and `api_key=...` inside summaries/details.
- Context output projects only summary + refs + severity/status/error/warnings.
- Audit output keeps `error_type` but redacts raw secret values.
- Raw payload/evidence/positions are converted to safe summary keys such as `tool_payload_summary`, `evidence_summary`, and `positions_summary`.

## ObservationWindow 裁剪规则

- Blocking observations are always retained.
- Approval required/denied, tool errors, permission blocked, context/evidence insufficient, task failed and clarification-needed observations are required.
- Old observations are summarized as `ObservationSummary`.
- Tool-only large objects are represented by summary + refs.

## MessageBus 接入点

- Not connected in this stage.
- Existing `MessageType.OBSERVATION_CREATED` remains available for later Phase 15-C/D integration.

## ContextManager 接入点

- Not connected in this stage.
- Planned later: Context receives observation refs only, never raw observation payloads.

## ToolExecutor 接入点

- Not connected in this stage.
- Planned later: ToolExecutor maps `UnifiedToolResult` to `ObservationEvent`.

## WriteGateway 边界说明

- No WriteGateway code changed.
- ReAct/Observation model has no commit or business write capability.

## MemoryTool readonly 边界说明

- No MemoryManager or MemoryTool behavior changed.
- MemoryTool remains readonly.

## AI Agent 加载优化结果

- Not changed in this stage.
- Page behavior intentionally remains unchanged.

## 兼容旧接口说明

- No existing imports or dict paths were removed.
- Existing Message/Context/Memory policy tests continue to pass.

## 测试命令与结果

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts` -> PASS
- `py -3 -m pytest tests/unit/test_phase15_observation_core.py -q` -> PASS, 4 passed
- `py -3 -m pytest tests/unit/test_phase15_observe_policy.py -q` -> PASS, 5 passed
- `py -3 -m pytest tests/unit/test_phase13_message_policy.py tests/unit/test_phase13_message_core.py -q` -> PASS, 6 passed
- `py -3 -m pytest tests/unit/test_phase14_memory_policy.py tests/unit/test_phase12_context_policy.py -q` -> PASS, 8 passed
- `py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q` -> PASS, 7 passed

## 真实网页检查结果

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = health endpoint + `scripts/check_phase13_communication_web.py` + Playwright Chromium real render + in-app browser inspection

WEB_CHECK_PAGES = [
  "http://127.0.0.1:8501/_stcore/health",
  "首页 / 预测排名",
  "AI Agent 页面",
  "AI 模拟盘页面",
  "系统监控页面"
]

WEB_CHECK_RESULT = PASS

WEB_CHECK_ERRORS = []

## 失败项

- Initial sanitizer test found inline `confirmation_token=...` in summary text. Fixed by adding text-level redaction and safe summary key names.

## 未完成项

- ObserveStore, ReActTrace, and ReplanPolicy are not implemented until Phase 15-C.
- Executor/ToolExecutor/Context integration is not implemented until Phase 15-D.
- AI Agent loading optimization is not implemented until Phase 15-E.

NEXT_STAGE_ALLOWED = true
