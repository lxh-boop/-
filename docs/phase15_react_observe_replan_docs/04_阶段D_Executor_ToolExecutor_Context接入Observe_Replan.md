# Phase 15-D：Executor、ToolExecutor、ContextManager 接入 Observe / Replan

## 本阶段目标

把 ReAct Observe / Replan 接入主链，但保持兼容。

目标：

```text
ToolExecutor 工具调用结果生成 ObservationEvent
Executor 根据 ObservationEvent 评估是否需要 Replan
ContextManager 提供 observation refs / memory refs 给后续步骤
MessageBus 发布 OBSERVATION_CREATED / REPLAN_* 消息
Replan 只做受控局部修正或安全报告
旧 dict/result 路径保持兼容
```

---

## 一、允许做

1. 接入 agent/executor.py；
2. 接入 agent/tool_engine.py；
3. 接入 agent/context/；
4. 接入 agent/communication/；
5. 接入 agent/artifacts.py 的 ref；
6. 接入 agent/memory/ 的 readonly refs；
7. 增加主链集成测试；
8. 保持旧接口兼容。

---

## 二、禁止做

1. 不改变 UserGoal 分类口径；
2. 不改变 TaskPlan 原始规划结果格式；
3. 不改变 ToolExecutor 权限规则；
4. 不改变 WriteGateway 审批、revalidate、commit；
5. 不重写工具；
6. 不实现 Reflection Critic；
7. 不实现 Multi-Agent Handoff；
8. 不让 Replan 自动执行写操作；
9. 不让 Replan 绕过 confirmation；
10. 不大改 UI。

---

## 三、ToolExecutor 接入

工具调用前，原 Phase 13 消息保持：

```text
MessageBus.publish(TOOL_CALL_REQUESTED)
```

工具成功后：

```text
MessageBus.publish(TOOL_RESULT_RECEIVED)
create ObservationEvent(type=TOOL_SUCCESS or TOOL_EMPTY_RESULT)
ObserveStore.save_observation(...)
MessageBus.publish(OBSERVATION_CREATED)
```

工具失败后：

```text
MessageBus.publish(ERROR_RAISED)
create ObservationEvent(type=TOOL_ERROR)
ObserveStore.save_observation(...)
MessageBus.publish(OBSERVATION_CREATED)
```

要求：

```text
不改变 execute() 返回值
不改变 UnifiedToolResult 结构
不改变 ToolExecutor 权限规则
旧调用没有 ObserveStore / MessageBus 时自动 no-op
observation payload 只保存摘要 + refs
```

---

## 四、Executor 接入

Task 执行后：

```text
收集 task observations
ReplanPolicy.evaluate_observation(...)
```

如果不需要 replan：

```text
MessageBus.publish(REPLAN_SKIPPED)
继续原流程
```

如果需要 replan：

```text
build ReplanDecision
MessageBus.publish(REPLAN_REQUESTED)
检查 ReplanLimiter
如果允许：局部修正当前 task 或生成 clarification / block report
MessageBus.publish(REPLAN_APPLIED or REPLAN_BLOCKED)
```

要求：

```text
replan 只允许局部修正 CURRENT_TASK / DEPENDENT_TASKS
不能重写整个 planner
不能无限循环
不能自动提升权限
不能自动 commit
不能吞掉最终报告
```

---

## 五、ContextManager 接入

Context refs 中加入：

```text
observation_refs = {
  observation_ids,
  blocking_observation_ids,
  latest_replan_decision_id
}

memory_refs = {
  safe_summary_id,
  memory_search_refs
}
```

不得把完整 ObservationEvent、完整 MemoryRecord、完整 ContextBundle 放入 message payload 或 prompt。

---

## 六、MessageBus 接入

必须发布：

```text
OBSERVATION_CREATED
REPLAN_REQUESTED
REPLAN_SKIPPED
REPLAN_APPLIED
REPLAN_BLOCKED
```

消息 payload 要求：

```text
observation_id
replan_decision_id
status
reason
scope
summary
refs
```

不可显示：

```text
confirmation_token
api_key
db_path
local path
raw stack trace
raw tool payload
raw positions
raw evidence
```

---

## 七、WriteGateway 边界

如果 replan 结果涉及写操作：

```text
只能生成 proposal / pending approval
必须继续走 WriteGateway
必须继续走 revalidate
必须继续走 execute_confirmed_plan_v2
```

Replan 不得直接：

```text
commit paper trade
modify portfolio state
modify strategy state
write order
bypass confirmation token
```

---

## 八、测试

新增：

```text
tests/unit/test_phase15_observe_tool_executor_integration.py
tests/unit/test_phase15_replan_executor_integration.py
tests/unit/test_phase15_context_observation_refs.py
```

覆盖：

```text
ToolExecutor 成功生成 TOOL_SUCCESS observation
ToolExecutor 空结果生成 TOOL_EMPTY_RESULT observation
ToolExecutor 失败生成 TOOL_ERROR observation
MessageBus 产生 OBSERVATION_CREATED
Executor 对 empty result 生成 REPLAN_REQUESTED
Executor 对 success 生成 REPLAN_SKIPPED
ReplanLimiter 防止无限循环
Context refs 包含 observation_refs
Memory refs 只包含 safe summary / refs
confirmation_token 不进入 observation/message/context
旧调用无 ObserveStore 兼容
写操作仍需 WriteGateway
```

运行：

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase15_observe_tool_executor_integration.py -q
py -3 -m pytest tests/unit/test_phase15_replan_executor_integration.py -q
py -3 -m pytest tests/unit/test_phase15_context_observation_refs.py -q
py -3 -m pytest tests/unit/test_phase15_observe_store_trace.py -q
py -3 -m pytest tests/unit/test_phase15_replan_policy.py -q
py -3 -m pytest tests/unit/test_phase13_message_executor_integration.py -q
py -3 -m pytest tests/unit/test_phase13_message_tool_executor_integration.py -q
py -3 -m pytest tests/unit/test_phase13_message_write_gateway_integration.py -q
py -3 -m pytest tests/unit/test_phase14_memory_manager.py -q
py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q
py -3 -m pytest tests/unit/test_agent_write_requires_confirmation.py -q
py -3 -m pytest tests/unit/test_agent_action_proposal_gateway.py -q
```

---

## 九、真实网页功能检查

必须真实操作 AI Agent 页面。

检查：

```text
http://127.0.0.1:8501/_stcore/health
首页 / 预测排名
AI Agent 页面
AI 模拟盘页面
系统监控页面
```

AI Agent 页面实际测试：

```text
1. 输入：查看我的当前持仓
   期望：返回持仓或安全提示，不报错，并产生 OBSERVATION_CREATED / REPLAN_SKIPPED 或安全说明

2. 输入：分析当前组合风险
   期望：返回风险分析或安全提示，不报错，并产生 TOOL_CALL / TOOL_RESULT / OBSERVATION_CREATED

3. 输入：给我一个调仓建议
   期望：生成 proposal 或说明缺少信息，不直接执行；如需要审批，仍走 WriteGateway

4. 输入：查看系统状态
   期望：返回系统状态或安全提示，不报错

5. 输入：我上次为什么建议调仓？
   期望：使用 readonly memory/message refs 或说明暂无记录，不报错
```

记录：

```text
input
expected
actual_summary
observation_created
message_types_seen
replan_decision_seen
secret_visible
traceback_error
pass/fail
```

---

## 十、阶段报告

生成：

```text
docs/phase15_d_react_runtime_integration_report.md
```

必须包含：

```text
Executor 接入点
ToolExecutor 接入点
ContextManager 接入点
MessageBus 接入点
Memory refs 接入点
WriteGateway 边界说明
兼容旧接口说明
Observation 实际产生情况
ReplanDecision 实际产生情况
真实网页功能检查记录
测试结果
NEXT_STAGE_ALLOWED = true / false
```

---

## 十一、验收标准

1. ToolExecutor 发布 observation；
2. Executor 可以评估 observation；
3. MessageBus 发布 OBSERVATION_CREATED；
4. MessageBus 发布 REPLAN_*；
5. Context refs 包含 observation refs；
6. Memory refs 只读且安全；
7. secret 不进入 observation/message/context；
8. 旧接口兼容；
9. P0 WriteGateway 不破坏；
10. P1-A proposal 不破坏；
11. AI Agent 真实输入测试通过；
12. 页面不报错；
13. 测试通过；
14. NEXT_STAGE_ALLOWED = true。
