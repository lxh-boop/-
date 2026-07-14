# Phase 15-C Observe Store Replan Report

## 阶段目标

建立 observation 存储、ReAct trace 和受控 Replan 决策底座。本阶段未把所有业务链路切到 ReAct，仅新增可复用基础设施。

## 修改前状态表

| 检查项 | 修改前 | 本阶段结果 |
|---|---|---|
| ObserveStore | 不存在 | 已新增本地 jsonl store |
| ReActTrace/ReActStep | 不存在 | 已新增 |
| ReplanDecision/Reason/Scope | 不存在 | 已新增 |
| ReplanLimiter | 不存在 | 已新增 |
| MessageType Replan 兼容 | 只有 `OBSERVATION_CREATED` | 已最小补充 `REPLAN_REQUESTED/SKIPPED/APPLIED/BLOCKED` |
| 主执行链接入 | dict 型 observation / limited replan | 本阶段不深接，保持原行为 |

## 新增/修改文件

- Added `agent/react/observe_store.py`
- Added `agent/react/react_trace.py`
- Added `agent/react/replan_types.py`
- Added `agent/react/replan_policy.py`
- Modified `agent/react/__init__.py`
- Modified `agent/communication/message_types.py`
- Added `tests/unit/test_phase15_observe_store_trace.py`
- Added `tests/unit/test_phase15_replan_policy.py`

## ObserveStore 存储方式

- Uses local jsonl files under `outputs/react_logs/<user_id>/<run_id>.jsonl`.
- `save_observation()` sanitizes with `ObserveSanitizer.sanitize_for_audit()` before writing.
- Supports:
  - `save_observation()`
  - `load_observation()`
  - `list_observations_by_run()`
  - `list_observations_by_conversation()`
  - `list_observations_by_task()`
  - `list_blocking_observations()`
  - `expire_observations()`
- No business database schema was added.
- ObserveStore writes only observation audit logs, not simulated portfolio, strategy, approval, or commit state.

## ReActTrace 结构

- `trace_id`
- `run_id`
- `steps`
- `message_ids`
- `observation_ids`
- `tool_call_edges`
- `artifact_edges`
- `approval_edges`
- `memory_edges`
- `replan_edges`
- `errors`
- `warnings`

## ReActStep 结构

- `step_id`
- `run_id`
- `task_id`
- `thought_summary`
- `action_summary`
- `tool_name`
- `observation_id`
- `replan_decision_id`
- `status`
- `created_at`
- `refs`

`thought_summary` stores only a short operational summary, not private chain-of-thought.

## ReplanPolicy 规则

- TOOL_EMPTY_RESULT -> `tool_result_empty`, `CURRENT_TASK`, REQUESTED if under limits.
- TOOL_ERROR -> recoverable unless severity is BLOCKING.
- CONTEXT_INSUFFICIENT -> `missing_required_context`, `DEPENDENT_TASKS`.
- EVIDENCE_INSUFFICIENT -> `evidence_insufficient`, `DEPENDENT_TASKS`.
- APPROVAL_REQUIRED -> WAIT_APPROVAL, `write_gateway_required`, `auto_commit=false`.
- APPROVAL_DENIED -> BLOCK_AND_REPORT.
- TOOL_PERMISSION_BLOCKED -> BLOCKED, `permission_escalation_disallowed`.
- TOOL_SUCCESS / REPORT_READY / MEMORY_HIT -> SKIPPED, `NO_REPLAN`.

## ReplanLimiter 规则

- Per run max replans default: 2.
- Per task max replans default: 1.
- Same run/task/reason repeat max default: 1.
- If limit is reached, decision becomes BLOCKED with reason `max_replan_limit_reached`.
- The limiter never escalates permissions and never commits writes.

## MessageType 兼容情况

Existing:

- `OBSERVATION_CREATED`

Added:

- `REPLAN_REQUESTED`
- `REPLAN_SKIPPED`
- `REPLAN_APPLIED`
- `REPLAN_BLOCKED`

No MessageBus route behavior was changed in this stage.

## ContextManager 接入点

- Not connected in this stage.
- Planned later: Context receives observation refs and replan refs only.

## ToolExecutor 接入点

- Not connected in this stage.
- Planned later: ToolExecutor creates `ObservationEvent` after `UnifiedToolResult`.

## WriteGateway 边界说明

- ReplanPolicy never commits writes.
- `APPROVAL_REQUIRED` produces WAIT_APPROVAL and includes `write_gateway_required`.
- `metadata.auto_commit` is always false.

## MemoryTool readonly 边界说明

- MemoryTool was not changed.
- ReplanPolicy does not write memory or business state.

## AI Agent 加载优化结果

- Not changed in this stage.

## 兼容旧接口说明

- Existing dict observations in `multi_task_executor` remain untouched.
- Existing MessageBus and MessageStore tests pass after enum extension.

## 测试命令与结果

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts` -> PASS
- `py -3 -m pytest tests/unit/test_phase15_observe_store_trace.py -q` -> PASS, 4 passed
- `py -3 -m pytest tests/unit/test_phase15_replan_policy.py -q` -> PASS, 6 passed
- `py -3 -m pytest tests/unit/test_phase15_observation_core.py tests/unit/test_phase15_observe_policy.py -q` -> PASS, 9 passed
- `py -3 -m pytest tests/unit/test_phase13_message_store_bus.py tests/unit/test_phase13_message_policy.py -q` -> PASS, 6 passed
- `py -3 -m pytest tests/unit/test_phase14_memory_manager.py -q` -> PASS, 5 passed
- `py -3 -m pytest tests/unit/test_phase12_context_executor_integration.py -q` -> PASS, 2 passed

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

- Initial `TOOL_SUCCESS` replan test found status skipped but scope still `CURRENT_TASK`. Fixed to return `NO_REPLAN`.

## 未完成项

- Executor/ToolExecutor/Context integration is deferred to Phase 15-D.
- AI Agent loading optimization is deferred to Phase 15-E.

NEXT_STAGE_ALLOWED = true
