# Phase 15-D ReAct Runtime Integration Report

## 阶段目标

把 ReAct Observe / Replan 以最小侵入方式接入 ToolExecutor、Executor 和 Context refs。保持旧 dict/result 路径、ToolExecutor 权限规则、WriteGateway 审批/revalidate/commit 边界不变。

## 修改前状态表

| 检查项 | 修改前 | 本阶段结果 |
|---|---|---|
| ToolExecutor observation | 只发布 Phase13 tool messages | 成功/空/异常结果旁路生成 ObservationEvent |
| Executor replan evaluation | 无标准 ReplanDecision | 顶层 result observation 旁路生成 ReplanDecision |
| Context observation refs | 无 | `RuntimeContext` 增加 observation/replan refs |
| MessageBus ReAct messages | enum 已有/预留 | 实际发布 OBSERVATION_CREATED 和 REPLAN_* |
| WriteGateway | 已有确认闭环 | 未修改，Replan 不 commit |

## 新增/修改文件

- Added `agent/react/integration.py`
- Modified `agent/tool_engine.py`
- Modified `agent/executor.py`
- Modified `agent/context/context_types.py`
- Modified `agent/context/context_policy.py`
- Added `tests/unit/test_phase15_observe_tool_executor_integration.py`
- Added `tests/unit/test_phase15_replan_executor_integration.py`
- Added `tests/unit/test_phase15_context_observation_refs.py`

## Executor 接入点

- `agent/executor.py` imports `record_executor_result_observation`.
- After `result_dict` is produced and Context is updated, Executor records a top-level `ObservationEvent`.
- The helper evaluates it through `ReplanPolicy`, publishes `OBSERVATION_CREATED` and `REPLAN_*`, and attaches observation/replan refs to the existing ContextBundle.
- If observation recording fails, the original request flow continues with a `phase15_observation_failed:*` warning.

## ToolExecutor 接入点

- `agent/tool_engine.py` imports `record_tool_observation`.
- After `TOOL_RESULT_RECEIVED`, ToolExecutor records an observation and replan decision.
- Handler exceptions are converted to existing `UnifiedToolResult` failures, then recorded as TOOL_ERROR observations.
- `execute()` return value and `UnifiedToolResult` structure are unchanged.

## ContextManager 接入点

`RuntimeContext` now has:

- `observation_refs`
- `blocking_observation_ids`
- `replan_refs`
- `latest_replan_decision_id`

`ContextBundle.to_minimal_context()` returns refs only. It does not include full ObservationEvent, raw tool payload, raw evidence, raw positions, or MemoryRecord payloads.

## MessageBus 接入点

Published by `agent/react/integration.py`:

- `OBSERVATION_CREATED`
- `REPLAN_REQUESTED`
- `REPLAN_SKIPPED`
- `REPLAN_APPLIED`
- `REPLAN_BLOCKED`

Payload contains only:

- observation_id / replan_decision_id
- status
- reason
- scope
- summary
- refs
- blocked_by

## Memory refs 接入点

- Existing Memory safe refs and safe summary remain unchanged.
- ReAct integration does not write memory and does not load full MemoryRecord payloads.

## WriteGateway 边界说明

- ReplanPolicy metadata keeps `auto_commit=false`.
- `APPROVAL_REQUIRED` becomes `WAIT_APPROVAL` with `write_gateway_required`.
- Replan never calls commit tools, never modifies portfolio state, and never bypasses confirmation.
- Phase 11 WriteGateway and Agent write-confirmation tests pass.

## 兼容旧接口说明

- `ToolExecutor.execute()` still returns `UnifiedToolResult`.
- `execute_tool_legacy_dict()` and old dict result paths still work.
- Existing Phase13 MessageBus behavior remains compatible.
- Existing context minimal payload shape is extended with refs only.

## Observation 实际产生情况

Unit tests confirmed:

- Tool success -> TOOL_SUCCESS observation + OBSERVATION_CREATED + REPLAN_SKIPPED.
- Tool empty result -> TOOL_EMPTY_RESULT observation + REPLAN_REQUESTED.
- Tool exception -> TOOL_ERROR observation + OBSERVATION_CREATED.
- Executor success -> REPORT_READY observation + REPLAN_SKIPPED.
- Executor failure -> TASK_FAILED observation + REPLAN_REQUESTED.

## ReplanDecision 实际产生情况

Unit tests confirmed:

- Success result -> SKIPPED / NO_REPLAN.
- Empty result -> REQUESTED / tool_result_empty.
- Failure -> REQUESTED / task_dependency_failed or tool error reason.
- Approval required remains WAIT_APPROVAL and does not auto commit.
- Permission blocked remains BLOCKED and does not escalate permission.

## 真实网页功能检查记录

AI Agent AppTest used a temp DB/output directory and read message/react logs after each input.

| input | expected | actual_summary | observation_created | message_types_seen | replan_decision_seen | secret_visible | traceback_error | pass |
|---|---|---|---|---|---|---|---|---|
| 查看我的当前持仓 | portfolio state or safe fallback | returned safe Agent response with message trace and memory summary | true | USER_REQUEST, CONTEXT_CREATED, GOAL_PARSED, TASK_PLANNED, OBSERVATION_CREATED, REPLAN_SKIPPED, FINAL_REPORT | true | false | false | true |
| 分析当前组合风险 | risk analysis or safe fallback | returned safe Agent response with message trace and memory summary | true | USER_REQUEST, CONTEXT_CREATED, GOAL_PARSED, TASK_PLANNED, OBSERVATION_CREATED, REPLAN_SKIPPED, FINAL_REPORT | true | false | false | true |
| 给我一个调仓建议 | proposal or safe explanation, no direct commit | returned safe Agent response; no direct commit | true | USER_REQUEST, CONTEXT_CREATED, GOAL_PARSED, TASK_PLANNED, OBSERVATION_CREATED, REPLAN_SKIPPED, FINAL_REPORT | true | false | false | true |
| 查看系统状态 | system status or safe fallback | returned safe Agent response with message trace and memory summary | true | USER_REQUEST, CONTEXT_CREATED, GOAL_PARSED, TASK_PLANNED, OBSERVATION_CREATED, REPLAN_SKIPPED, FINAL_REPORT | true | false | false | true |
| 我上次为什么建议调仓？ | readonly memory/message refs or no-record explanation | returned safe Agent response with message trace and memory summary | true | USER_REQUEST, CONTEXT_CREATED, GOAL_PARSED, TASK_PLANNED, OBSERVATION_CREATED, REPLAN_SKIPPED, FINAL_REPORT | true | false | false | true |

## 测试命令与结果

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts` -> PASS
- `py -3 -m pytest tests/unit/test_phase15_observe_tool_executor_integration.py -q` -> PASS, 3 passed
- `py -3 -m pytest tests/unit/test_phase15_replan_executor_integration.py -q` -> PASS, 3 passed
- `py -3 -m pytest tests/unit/test_phase15_context_observation_refs.py -q` -> PASS, 2 passed
- `py -3 -m pytest tests/unit/test_phase15_observe_store_trace.py tests/unit/test_phase15_replan_policy.py -q` -> PASS, 10 passed
- `py -3 -m pytest tests/unit/test_phase13_message_executor_integration.py tests/unit/test_phase13_message_tool_executor_integration.py tests/unit/test_phase13_message_write_gateway_integration.py -q` -> PASS, 4 passed
- `py -3 -m pytest tests/unit/test_phase14_memory_manager.py tests/unit/test_phase11_p0_write_gateway.py -q` -> PASS, 11 passed
- `py -3 -m pytest tests/unit/test_agent_write_requires_confirmation.py tests/unit/test_agent_action_proposal_gateway.py -q` -> PASS, 4 passed

## 真实网页检查结果

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = health endpoint + Streamlit AppTest AI Agent inputs + `scripts/check_phase13_communication_web.py` + Playwright Chromium real render + in-app browser inspection

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

- Initial integration test found token-like text inside `error_message` could land in observation audit logs. Fixed text-level ObserveSanitizer regex to redact `token <value>` as well as `token=<value>`.

## 未完成项

- AI Agent loading optimization and Memory view lightweight loading are deferred to Phase 15-E.
- Replan currently creates safe decisions/messages; it does not rewrite the whole planner or execute write actions.

NEXT_STAGE_ALLOWED = true
