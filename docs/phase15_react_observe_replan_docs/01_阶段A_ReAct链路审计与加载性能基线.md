# Phase 15-A：ReAct 链路审计与加载性能基线

## 本阶段目标

本阶段先不要大规模改代码，重点是把当前项目中可以生成 Observation 的位置、可以触发 Replan 的位置、以及 AI Agent 页面加载慢的真实原因查清楚。

目标：

```text
找出 ToolExecutor 工具结果如何返回
找出 UnifiedToolResult / Artifact / MessageTrace 如何进入最终回答
找出 Executor 当前如何处理失败、空结果、参数缺失、权限不足
找出 ContextManager 当前如何裁剪上下文
找出 MemoryTool safe summary 当前如何进入 UI / Context
找出 AI Agent 页面当前如何加载历史对话
找出 message trace / tool details / evidence / memory summary 当前是否全量渲染
建立 ReAct Observe / Replan 目标接入表
建立加载性能基线表
```

本阶段只允许审计、记录、轻量 instrumentation，不允许接入完整 ReAct 或大改 UI。

---

## 一、允许做

1. 搜索和阅读代码；
2. 新增 ReAct / loading 审计报告；
3. 设计 Observation 来源表；
4. 设计 Replan 触发点表；
5. 设计加载性能基线表；
6. 可新增轻量计时 helper，但不得改变业务行为；
7. 可新增 `agent/react/README.md` 或设计草案；
8. 可新增空包或类型草案，但不要接入主链。

---

## 二、禁止做

1. 不接入 executor 主链；
2. 不改 ToolExecutor 行为；
3. 不改 WriteGateway；
4. 不改 ContextManager 行为；
5. 不改 MemoryManager；
6. 不改变 AI Agent 用户操作流程；
7. 不实现完整 ReAct；
8. 不实现 Reflection；
9. 不实现 Multi-Agent Handoff；
10. 不删除旧 dict / result 路径；
11. 不改变业务结果；
12. 不用加载优化掩盖功能错误。

---

## 三、必须检查的文件

```text
agent/executor.py
agent/tool_engine.py
agent/write_gateway.py
agent/context/
agent/communication/
agent/memory/
agent/artifacts.py
agent/runtime.py
agent/runtime_reliability.py
agent/goal_planning.py
agent/intent_decomposition/
agent/orchestration/multi_task_executor.py
agent/specialists/
agent/tools/
agent/services/
app/pages/ai_agent.py
app/pages/system_monitor.py
app/pages/ai_paper_trading.py
app.py
database/repositories/
scripts/check_phase13_communication_web.py
```

---

## 四、必须输出 ReAct 链路审计表

生成：

```text
docs/phase15_a_react_loading_audit_report.md
```

表格字段：

```text
source
file
function_or_class
current_input
current_output
can_create_observation
planned_observation_type
can_trigger_replan
planned_replan_reason
contains_context
contains_artifact_ref
contains_tool_result
contains_memory_ref
contains_approval
contains_secret_risk
used_by_llm
used_by_ui
problem
migration_phase
```

至少覆盖：

```text
user request
ContextBundle
TaskPlan
ToolExecutor input
UnifiedToolResult
Artifact refs
Approval pending plan
confirmation result
MessageTrace
MemoryTool summary
warnings/errors
AI Agent page result rendering
AI Paper Trading page result rendering
multi_task_executor result passing
specialist agent result passing
```

---

## 五、必须输出加载性能基线表

表格字段：

```text
page
component
current_loading_strategy
query_count_estimate
render_count_estimate
rerun_sensitive
loads_full_history
loads_full_trace
loads_full_memory
loads_raw_tool_details
symptom
planned_optimization
migration_phase
```

至少覆盖：

```text
AI Agent 历史消息列表
AI Agent 当前输入框
AI Agent message trace 展示
AI Agent developer details
AI Agent tool details
AI Agent evidence details
AI Agent memory summary
系统监控 MemoryStore health
系统监控 MessageBus health
AI 模拟盘页面
```

---

## 六、ReAct Observe / Replan 初步设计

在报告中写出目标模型：

```text
ObservationEvent
ObservationType
ObservationStatus
ObservationSeverity
ObservePolicy
ObserveSanitizer
ObserveStore
ReActStep
ReActTrace
ReplanDecision
ReplanReason
ReplanScope
ReplanPolicy
```

建议 ObservationType：

```text
TOOL_SUCCESS
TOOL_EMPTY_RESULT
TOOL_ERROR
TOOL_PERMISSION_BLOCKED
CONTEXT_INSUFFICIENT
EVIDENCE_INSUFFICIENT
MEMORY_HIT
MEMORY_EMPTY
APPROVAL_REQUIRED
APPROVAL_DENIED
TASK_PARTIAL_SUCCESS
TASK_FAILED
REPORT_READY
```

建议 ReplanReason：

```text
missing_required_context
missing_required_parameter
tool_error_recoverable
tool_result_empty
evidence_insufficient
permission_blocked
approval_required
user_goal_changed
task_dependency_failed
max_context_budget_exceeded
```

注意：

```text
本阶段只设计，不实现完整逻辑。
```

---

## 七、真实网页基线检查

本阶段虽然不接入主链，也必须检查页面当前基线。

检查：

```text
http://127.0.0.1:8501/_stcore/health
首页 / 预测排名
AI Agent 页面
AI 模拟盘页面
系统监控页面
```

AI Agent 长对话基线：

```text
连续输入不少于 12 条消息
记录第 1 条、第 7 条、第 12 条后的体感/脚本耗时
记录页面是否出现卡顿、Traceback、KeyError、NameError
记录 message trace / memory summary 是否全量渲染
```

记录：

```text
WEB_CHECK_DONE = true
WEB_CHECK_METHOD
WEB_CHECK_PAGES
WEB_CHECK_RESULT
WEB_CHECK_ERRORS
LONG_CHAT_CHECK_DONE = true
LONG_CHAT_MESSAGE_COUNT
LOAD_BASELINE_SUMMARY
```

---

## 八、测试命令

运行：

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q
py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q
py -3 -m pytest tests/unit/test_phase12_context_core.py -q
py -3 -m pytest tests/unit/test_phase12_context_policy.py -q
py -3 -m pytest tests/unit/test_phase12_context_executor_integration.py -q
py -3 -m pytest tests/unit/test_phase13_message_core.py -q
py -3 -m pytest tests/unit/test_phase13_message_store_bus.py -q
py -3 -m pytest tests/unit/test_phase14_memory_manager.py -q
py -3 -m pytest tests/unit/test_phase14_memory_tool_ui.py -q
```

---

## 九、阶段报告

生成：

```text
docs/phase15_a_react_loading_audit_report.md
```

必须包含：

```text
ReAct 链路审计表
加载性能基线表
Observation 目标模型
Replan 目标模型
风险点
加载瓶颈判断
测试结果
网页检查结果
NEXT_STAGE_ALLOWED = true / false
```

---

## 十、验收标准

1. 完成 ReAct 链路审计表；
2. 完成加载性能基线表；
3. 完成 Observation 类型初步设计；
4. 完成 Replan 触发点初步设计；
5. 完成敏感字段风险识别；
6. 未破坏现有代码；
7. compileall 通过；
8. 回归测试通过；
9. 真实网页检查通过；
10. 长对话加载基线记录完成；
11. NEXT_STAGE_ALLOWED = true。
