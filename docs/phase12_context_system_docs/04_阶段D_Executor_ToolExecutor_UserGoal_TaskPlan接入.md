# Phase 12-D：Executor、ToolExecutor、UserGoal、TaskPlan 接入 ContextManager

## 本阶段目标

把 ContextManager 接入 Agent 主执行链，但保持兼容。

目标：

```text
executor 开始创建 ContextBundle
UserGoal Parser 可读取 ContextBundle
TaskPlanner 可读取 ContextBundle
ToolExecutor 可接收 ToolContext
工具结果更新 ContextBundle
报告生成可读取 report_context
旧调用无 ContextBundle 时自动 minimal context
```

---

## 一、允许做

1. 接入 agent/executor.py；
2. 接入 UserGoal / TaskPlan；
3. 接入 ToolExecutor；
4. 接入 Result Aggregator / Report；
5. 增加 minimal context 兼容；
6. 增加主链集成测试。

---

## 二、禁止做

1. 不改变 UserGoal 语义分类口径；
2. 不改变 TaskPlan 业务规划结果；
3. 不改变 ToolExecutor 权限规则；
4. 不改变写操作审批链；
5. 不重写工具；
6. 不大改 UI；
7. 不实现 MessageBus；
8. 不实现完整 MemoryManager。

---

## 三、接入 agent/executor.py

执行开始：

```text
context = ContextManager.create_initial_context(
    user_message,
    user_id,
    conversation_id,
    run_id,
)
```

任务规划前：

```text
goal_context = context_manager.build_goal_context(context)
```

任务执行前：

```text
tool_context = context_manager.build_tool_context(task, context)
```

工具执行后：

```text
context_manager.update_from_tool_result(context, tool_result)
```

报告前：

```text
report_context = context_manager.build_report_context(context)
```

---

## 四、接入 ToolExecutor

ToolExecutor 支持：

```text
execute(tool_name, tool_input, context_bundle=None, tool_context=None)
```

兼容：

```text
如果 context_bundle is None，则 create_minimal_context()
```

ToolExecutor 不能破坏旧测试。

---

## 五、接入 UserGoal / TaskPlan

UserGoal Parser 可读取：

```text
UserContext
ConversationContext
ArtifactContext refs
ApprovalContext summary
```

TaskPlanner 可读取：

```text
TaskContext
ArtifactContext
required_context
available_context_refs
```

Planner 不直接查数据库。

---

## 六、工具上下文规则

工具只能读取：

```text
ToolContext 中授权字段
artifact_refs
source_refs
permission_scope
runtime_budget
```

禁止工具直接读取：

```text
Streamlit session_state
全局 current_user
未授权 artifact
SECRET 字段
```

---

## 七、测试

新增：

```text
tests/unit/test_phase12_context_executor_integration.py
tests/unit/test_phase12_context_tool_executor.py
```

覆盖：

```text
executor 创建 ContextBundle
UserGoal 可读取 ContextBundle
TaskPlan 可读取 ContextBundle
ToolExecutor 接收 ToolContext
工具结果更新 ArtifactContext
旧调用未传 context 仍兼容
P0 Write Gateway 不破坏
P1-A proposal 不破坏
```

运行：

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase12_context_executor_integration.py -q
py -3 -m pytest tests/unit/test_phase12_context_tool_executor.py -q
py -3 -m pytest tests/unit/test_phase12_context_store_resolver.py -q
py -3 -m pytest tests/unit/test_phase12_context_core.py -q
py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q
py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q
py -3 -m pytest tests/unit/test_agent_write_requires_confirmation.py -q
py -3 -m pytest tests/unit/test_agent_action_proposal_gateway.py -q
py -3 -m pytest tests/unit/test_phase10_goal_planning.py -q
py -3 -m pytest tests/unit/test_phase10_3_capability_artifacts.py -q
```

---

## 八、真实网页功能检查

必须真实操作 AI Agent 页面。

检查：

```text
http://127.0.0.1:8501/_stcore/health
首页
AI Agent 页面
AI 模拟盘页面
系统监控页面
```

AI Agent 页面必须实际测试：

```text
1. 输入：查看我的当前持仓
   期望：返回持仓或安全提示，不报错

2. 输入：分析当前组合风险
   期望：返回风险分析或安全提示，不报错

3. 输入：给我一个调仓建议
   期望：能生成 proposal 或说明缺少信息，不直接执行

4. 如果有 pending plan：
   检查待确认区域仍可见
```

记录每个输入的：

```text
input
expected
actual_summary
pass/fail
error
```

---

## 九、阶段报告

生成：

```text
docs/phase12_d_context_executor_integration_report.md
```

必须包含：

```text
executor 接入点
ToolExecutor 接入点
UserGoal/TaskPlan 接入点
兼容旧接口说明
真实网页功能检查记录
测试结果
NEXT_STAGE_ALLOWED = true / false
```

---

## 十、验收标准

1. executor 创建 ContextBundle；
2. UserGoal 可读 ContextBundle；
3. TaskPlan 可读 ContextBundle；
4. ToolExecutor 可接收 ToolContext；
5. 工具结果可更新 ContextBundle；
6. 旧调用 minimal context 兼容；
7. P0 Write Gateway 不破坏；
8. P1-A proposal 不破坏；
9. AI Agent 真实输入测试通过；
10. 页面不报错；
11. 测试通过；
12. NEXT_STAGE_ALLOWED = true。
