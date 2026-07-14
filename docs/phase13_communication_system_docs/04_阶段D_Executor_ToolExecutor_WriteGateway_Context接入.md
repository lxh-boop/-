# Phase 13-D：Executor、ToolExecutor、WriteGateway、ContextManager 接入 MessageBus

## 本阶段目标

把通信系统接入主链，但保持兼容。

目标：

```text
Executor 发布 USER_REQUEST / CONTEXT_CREATED / GOAL_PARSED / TASK_PLANNED / FINAL_REPORT
ToolExecutor 发布 TOOL_CALL_REQUESTED / TOOL_RESULT_RECEIVED / ARTIFACT_CREATED / ERROR_RAISED
WriteGateway 发布 APPROVAL_REQUESTED / APPROVAL_RESULT_RECEIVED
ContextManager 提供 context refs 给消息
消息进入 MessageStore
旧 dict/result 路径保持兼容
```

---

## 一、允许做

1. 接入 agent/executor.py；
2. 接入 agent/tool_engine.py；
3. 接入 agent/write_gateway.py；
4. 接入 agent/context/；
5. 接入 agent/artifacts.py 的 ref；
6. 增加主链集成测试；
7. 保持旧接口兼容。

---

## 二、禁止做

1. 不改变 UserGoal 分类口径；
2. 不改变 TaskPlan 规划结果；
3. 不改变 ToolExecutor 权限规则；
4. 不改变 WriteGateway 审批、revalidate、commit；
5. 不重写工具；
6. 不实现完整 ReAct；
7. 不实现完整 Reflection；
8. 不实现完整 Multi-Agent；
9. 不大改 UI。

---

## 三、Executor 接入

执行开始：

```text
MessageBus.publish(USER_REQUEST)
ContextManager.create_initial_context(...)
MessageBus.publish(CONTEXT_CREATED)
```

UserGoal 完成：

```text
MessageBus.publish(GOAL_PARSED)
```

TaskPlan 完成：

```text
MessageBus.publish(TASK_PLANNED)
```

最终结果：

```text
MessageBus.publish(FINAL_REPORT)
```

要求：

```text
message payload 只保存摘要 + refs
context_id 放入 context_refs
artifact_refs 放入 artifact_refs
approval_refs 放入 approval_refs
```

---

## 四、ToolExecutor 接入

工具调用前：

```text
MessageBus.publish(TOOL_CALL_REQUESTED)
```

工具成功后：

```text
MessageBus.publish(TOOL_RESULT_RECEIVED)
MessageBus.publish(ARTIFACT_CREATED)
```

工具失败后：

```text
MessageBus.publish(ERROR_RAISED)
```

要求：

```text
不改变 execute() 返回值
不改变 UnifiedToolResult 结构
不改变 ToolExecutor 权限规则
旧调用没有 MessageBus 时自动 no-op
```

---

## 五、WriteGateway 接入

生成/确认写操作时发布：

```text
APPROVAL_REQUESTED
APPROVAL_RESULT_RECEIVED
```

要求：

```text
不能暴露 confirmation_token 原文
只能传 plan_id / token_present / approval_status / plan_hash / summary
commit 仍走 execute_confirmed_plan_v2
MessageBus 不直接 commit
```

---

## 六、ContextManager 接入

消息中引用：

```text
context_refs = {
  context_id,
  run_id,
  conversation_id,
  task_id
}
```

不得把完整 ContextBundle 放入消息 payload。

---

## 七、Artifact 接入

消息中引用：

```text
artifact_refs = [
  artifact_id,
  artifact_type,
  produced_outputs
]
```

不得暴露 artifact path。

---

## 八、测试

新增：

```text
tests/unit/test_phase13_message_executor_integration.py
tests/unit/test_phase13_message_tool_executor_integration.py
tests/unit/test_phase13_message_write_gateway_integration.py
```

覆盖：

```text
executor 发布 USER_REQUEST
executor 发布 CONTEXT_CREATED
executor 发布 GOAL_PARSED
executor 发布 TASK_PLANNED
executor 发布 FINAL_REPORT
ToolExecutor 发布 TOOL_CALL_REQUESTED
ToolExecutor 发布 TOOL_RESULT_RECEIVED
ToolExecutor 失败发布 ERROR_RAISED
WriteGateway 发布 APPROVAL_REQUESTED / APPROVAL_RESULT_RECEIVED
confirmation_token 不进入 message
旧调用无 MessageBus 兼容
```

运行：

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase13_message_executor_integration.py -q
py -3 -m pytest tests/unit/test_phase13_message_tool_executor_integration.py -q
py -3 -m pytest tests/unit/test_phase13_message_write_gateway_integration.py -q
py -3 -m pytest tests/unit/test_phase13_message_store_bus.py -q
py -3 -m pytest tests/unit/test_phase13_message_policy.py -q
py -3 -m pytest tests/unit/test_phase12_context_executor_integration.py -q
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
   期望：返回持仓或安全提示，不报错，并产生 USER_REQUEST / FINAL_REPORT 消息

2. 输入：分析当前组合风险
   期望：返回风险分析或安全提示，不报错，并产生 TOOL_CALL / TOOL_RESULT 消息

3. 输入：给我一个调仓建议
   期望：生成 proposal 或说明缺少信息，不直接执行，并产生 APPROVAL_REQUESTED 或 proposal 相关消息

4. 输入：查看系统状态
   期望：返回系统状态或安全提示，不报错
```

记录：

```text
input
expected
actual_summary
message_created
message_types_seen
secret_visible
traceback_error
pass/fail
```

---

## 十、阶段报告

生成：

```text
docs/phase13_d_message_integration_report.md
```

必须包含：

```text
Executor 接入点
ToolExecutor 接入点
WriteGateway 接入点
ContextManager 接入点
Artifact 接入点
兼容旧接口说明
消息类型实际产生情况
真实网页功能检查记录
测试结果
NEXT_STAGE_ALLOWED = true / false
```

---

## 十一、验收标准

1. Executor 发布核心消息；
2. ToolExecutor 发布工具消息；
3. WriteGateway 发布审批消息；
4. Context refs 进入消息；
5. Artifact refs 进入消息；
6. secret 不进入消息；
7. 旧接口兼容；
8. P0 WriteGateway 不破坏；
9. P1-A proposal 不破坏；
10. AI Agent 真实输入测试通过；
11. 页面不报错；
12. 测试通过；
13. NEXT_STAGE_ALLOWED = true。
