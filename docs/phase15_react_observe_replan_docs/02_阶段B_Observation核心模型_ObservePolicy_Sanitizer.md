# Phase 15-B：Observation 核心模型、ObservePolicy、ObserveSanitizer

## 本阶段目标

建立 ReAct Observe 的核心观察模型和安全策略，但暂不深度接入主执行链。

目标：

```text
新增 agent/react/
新增 ObservationEvent
新增 ObservationType / ObservationStatus / ObservationSeverity
新增 ObservePolicy
新增 ObserveSanitizer
新增 ObservationSummary / ObservationWindow
保证 observation 可序列化、可脱敏、可裁剪、可审计
```

---

## 一、允许做

1. 新增 `agent/react/`；
2. 新增 observation 数据类；
3. 新增 observation 枚举；
4. 新增 ObservePolicy；
5. 新增 ObserveSanitizer；
6. 新增 ObservationWindow；
7. 新增基础单元测试；
8. 保持旧接口兼容。

---

## 二、禁止做

1. 不接入 executor 主链；
2. 不改 ToolExecutor 默认行为；
3. 不改 WriteGateway；
4. 不改 ContextManager；
5. 不改 MemoryManager；
6. 不实现 Reflection Critic；
7. 不实现 Multi-Agent Handoff；
8. 不大改 UI；
9. 不让 Observation 写业务状态。

---

## 三、建议新增文件

```text
agent/react/__init__.py
agent/react/observation_types.py
agent/react/observe_policy.py
agent/react/observe_sanitizer.py
agent/react/observation_window.py
```

---

## 四、核心模型

### 1. ObservationEvent

建议字段：

```text
observation_id
conversation_id
run_id
task_id
parent_task_id
source_message_id
source_tool_name
observation_type
status
severity
created_at
summary
detail
context_refs
artifact_refs
message_refs
memory_refs
approval_refs
tool_call_refs
source_refs
error
warnings
metadata
```

要求：

```text
可序列化
可脱敏
可裁剪
可审计
可建立 ReAct step 链路
可携带 context_id / artifact_ref / approval_ref / memory_ref
不直接携带大型原始对象
```

### 2. ObservationType

至少包含：

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
USER_CLARIFICATION_NEEDED
SYSTEM_WARNING
```

### 3. ObservationStatus

```text
CREATED
RECORDED
CONSUMED
IGNORED
FAILED
EXPIRED
```

### 4. ObservationSeverity

```text
INFO
LOW
MEDIUM
HIGH
BLOCKING
```

---

## 五、ObservePolicy

必须实现：

```text
classify_field()
classify_observation()
can_show_to_llm()
can_show_to_ui()
can_store()
requires_replan_check()
requires_redaction()
```

规则：

```text
confirmation_token -> SECRET
api_key / tushare_token / password / secret -> SECRET
db_path / database_path / local path -> SYSTEM_ONLY
stack_trace / traceback -> AUDIT_ONLY
raw_positions / raw_evidence / raw_tool_payload / full_payload -> TOOL_ONLY
summary / refs / token_present / status -> LLM_VISIBLE
```

Replan 检查规则：

```text
TOOL_EMPTY_RESULT -> requires_replan_check = true
TOOL_ERROR -> requires_replan_check = true
CONTEXT_INSUFFICIENT -> requires_replan_check = true
EVIDENCE_INSUFFICIENT -> requires_replan_check = true
TOOL_PERMISSION_BLOCKED -> requires_replan_check = true
APPROVAL_REQUIRED -> requires_replan_check = true
TOOL_SUCCESS -> usually false
REPORT_READY -> false
```

---

## 六、ObserveSanitizer

必须实现：

```text
sanitize_for_llm()
sanitize_for_ui()
sanitize_for_context()
sanitize_for_audit()
```

要求：

```text
LLM 版本不含 secret
UI 版本不含 internal stack/path/token
Context 版本只含 summary + refs + severity
Audit 版本可保留错误类型，但不能保留原始 secret
```

---

## 七、ObservationWindow

必须实现：

```text
trim_observations_to_budget()
summarize_old_observations()
keep_required_observations()
estimate_observation_size()
```

要求：

```text
BLOCKING observation 保留
APPROVAL_REQUIRED 摘要保留
TOOL_ERROR 摘要保留
TOOL_RESULT 只保留 summary + artifact_ref
大对象只保留 ref
```

---

## 八、测试

新增：

```text
tests/unit/test_phase15_observation_core.py
tests/unit/test_phase15_observe_policy.py
```

覆盖：

```text
ObservationEvent 可创建
ObservationEvent 可序列化
ObservationType 完整
secret 不进入 LLM
confirmation_token 不进入 LLM/UI
DB path 不进入 LLM/UI
stack trace 不进入 LLM/UI
raw payload 只保留 ref
ObservationWindow 保留 blocking observations
requires_replan_check 规则正确
```

运行：

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase15_observation_core.py -q
py -3 -m pytest tests/unit/test_phase15_observe_policy.py -q
py -3 -m pytest tests/unit/test_phase13_message_policy.py -q
py -3 -m pytest tests/unit/test_phase13_message_core.py -q
py -3 -m pytest tests/unit/test_phase14_memory_policy.py -q
py -3 -m pytest tests/unit/test_phase12_context_policy.py -q
py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q
```

---

## 九、真实网页检查

检查：

```text
http://127.0.0.1:8501/_stcore/health
首页 / 预测排名
AI Agent 页面
AI 模拟盘页面
系统监控页面
```

本阶段未接入主链，页面行为应保持不变。

---

## 十、阶段报告

生成：

```text
docs/phase15_b_observation_core_report.md
```

必须包含：

```text
新增文件
Observation 模型
Observation 类型
ObservePolicy 规则
ObserveSanitizer 结果
ObservationWindow 裁剪规则
测试结果
网页检查结果
NEXT_STAGE_ALLOWED = true / false
```

---

## 十一、验收标准

1. agent/react 包建立；
2. ObservationEvent 建立；
3. ObservationType 建立；
4. ObservationStatus 建立；
5. ObservationSeverity 建立；
6. ObservePolicy 建立；
7. ObserveSanitizer 建立；
8. ObservationWindow 建立；
9. secret 不进 LLM/UI；
10. 大对象摘要+ref；
11. compileall 通过；
12. 单测通过；
13. 真实网页检查通过；
14. NEXT_STAGE_ALLOWED = true。
