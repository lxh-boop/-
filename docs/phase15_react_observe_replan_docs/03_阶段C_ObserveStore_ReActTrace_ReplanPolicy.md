# Phase 15-C：ObserveStore、ReActTrace、ReplanPolicy

## 本阶段目标

建立 observation 存储、ReAct trace 和受控 replan 决策能力，但仍以轻量本地实现为主。

目标：

```text
ObserveStore
ReActStep
ReActTrace
ReplanDecision
ReplanReason
ReplanScope
ReplanPolicy
ReplanLimiter
```

本阶段可以建立可用的 ReAct Observe / Replan 底座，但不要强行把所有业务链路一次性切过来。

---

## 一、允许做

1. 新增 ObserveStore；
2. 新增 ReActTrace；
3. 新增 ReActStep；
4. 新增 ReplanDecision；
5. 新增 ReplanPolicy；
6. 新增 ReplanLimiter；
7. 增加 observation 查询；
8. 增加单测。

---

## 二、禁止做

1. 不引入外部队列；
2. 不引入 Redis / Kafka / Celery；
3. 不改业务算法；
4. 不让 ObserveStore 直接写业务状态；
5. 不让 ReplanPolicy 绕过 ToolExecutor；
6. 不让 ReplanPolicy 绕过 WriteGateway；
7. 不实现 Reflection Critic；
8. 不实现 Multi-Agent Handoff；
9. 不大改 UI。

---

## 三、建议新增文件

```text
agent/react/observe_store.py
agent/react/react_trace.py
agent/react/replan_policy.py
agent/react/replan_types.py
```

---

## 四、ObserveStore

必须支持：

```text
save_observation()
load_observation()
list_observations_by_run()
list_observations_by_conversation()
list_observations_by_task()
list_blocking_observations()
expire_observations()
```

存储方式：

```text
优先文件型或轻量 SQLite
可复用 outputs/react_logs/<user_id>/<run_id>.jsonl
不强制新增复杂 schema
如需 schema 变更，必须最小化并写入报告
```

保存前必须：

```text
sanitize_for_audit()
```

secret 不得原文落盘。

---

## 五、ReActTrace

必须支持：

```text
trace_id
run_id
steps
message_ids
observation_ids
tool_call_edges
artifact_edges
approval_edges
memory_edges
replan_edges
errors
warnings
```

ReActStep 建议字段：

```text
step_id
run_id
task_id
thought_summary
action_summary
tool_name
observation_id
replan_decision_id
status
created_at
refs
```

注意：

```text
thought_summary 只保存摘要，不保存私有推理链。
```

---

## 六、ReplanPolicy

必须支持：

```text
evaluate_observation()
should_replan()
build_replan_decision()
check_replan_limit()
summarize_replan_reason()
```

ReplanDecision 建议字段：

```text
replan_decision_id
conversation_id
run_id
task_id
trigger_observation_id
reason
scope
status
created_at
summary
suggested_plan_patch
blocked_by
message_refs
observation_refs
context_refs
artifact_refs
metadata
```

ReplanReason 至少包含：

```text
missing_required_context
missing_required_parameter
tool_error_recoverable
tool_error_blocking
tool_result_empty
evidence_insufficient
memory_insufficient
permission_blocked
approval_required
approval_denied
user_goal_changed
task_dependency_failed
max_context_budget_exceeded
max_replan_limit_reached
```

ReplanScope 至少包含：

```text
NO_REPLAN
CURRENT_TASK
DEPENDENT_TASKS
PLAN_SUMMARY_ONLY
ASK_USER_CLARIFICATION
BLOCK_AND_REPORT
```

---

## 七、Replan 限制

必须实现：

```text
单个 run 最大 replan 次数，默认 2
单个 task 最大 replan 次数，默认 1
同一 reason 不允许无限重复
approval_required 不得自动绕过审批
permission_blocked 不得自动升级权限
max_replan_limit_reached 时必须进入安全报告，而不是继续循环
```

---

## 八、MessageBus 预留接入

本阶段可以新增消息类型适配或 helper，但不要强行接主链。

需要兼容：

```text
OBSERVATION_CREATED
REPLAN_REQUESTED
REPLAN_SKIPPED
REPLAN_APPLIED
REPLAN_BLOCKED
```

如果 MessageType 中不存在，允许最小补充，并写入报告。

---

## 九、测试

新增：

```text
tests/unit/test_phase15_observe_store_trace.py
tests/unit/test_phase15_replan_policy.py
```

覆盖：

```text
save/load observation
list observations by run/conversation/task
secret 不落盘
ReActTrace 可追加 step
ReActTrace 可建立 observation edge
ReplanPolicy 对 empty result 触发 replan
ReplanPolicy 对 tool success 不触发 replan
ReplanLimiter 阻止无限 replan
approval_required 不自动 commit
```

运行：

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase15_observe_store_trace.py -q
py -3 -m pytest tests/unit/test_phase15_replan_policy.py -q
py -3 -m pytest tests/unit/test_phase15_observation_core.py -q
py -3 -m pytest tests/unit/test_phase15_observe_policy.py -q
py -3 -m pytest tests/unit/test_phase13_message_store_bus.py -q
py -3 -m pytest tests/unit/test_phase13_message_policy.py -q
py -3 -m pytest tests/unit/test_phase14_memory_manager.py -q
py -3 -m pytest tests/unit/test_phase12_context_executor_integration.py -q
```

---

## 十、真实网页检查

检查：

```text
http://127.0.0.1:8501/_stcore/health
首页 / 预测排名
AI Agent 页面
AI 模拟盘页面
系统监控页面
```

本阶段未深接主链，页面行为应保持不变。

---

## 十一、阶段报告

生成：

```text
docs/phase15_c_observe_store_replan_report.md
```

必须包含：

```text
ObserveStore 存储方式
ReActTrace 结构
ReActStep 结构
ReplanPolicy 规则
ReplanLimiter 规则
MessageType 兼容情况
测试结果
网页检查结果
NEXT_STAGE_ALLOWED = true / false
```

---

## 十二、验收标准

1. ObserveStore 建立；
2. ReActTrace 建立；
3. ReActStep 建立；
4. ReplanDecision 建立；
5. ReplanPolicy 建立；
6. ReplanLimiter 建立；
7. Observation 可落盘；
8. secret 不落盘；
9. empty/tool error 可触发 replan decision；
10. replan limit 生效；
11. approval_required 不绕过 WriteGateway；
12. 测试通过；
13. 真实网页检查通过；
14. NEXT_STAGE_ALLOWED = true。
