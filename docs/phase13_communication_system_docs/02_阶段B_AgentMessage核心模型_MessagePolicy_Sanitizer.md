# Phase 13-B：AgentMessage 核心模型、MessagePolicy、MessageSanitizer

## 本阶段目标

建立通信系统的核心消息模型和安全策略，但暂不深度接入主执行链。

目标：

```text
新增 agent/communication/
新增 AgentMessage / MessageEnvelope
新增 MessageType / MessageStatus / MessagePriority / MessageVisibility
新增 MessagePolicy
新增 MessageSanitizer
新增 MessageWindow / MessageSummary
保证消息可序列化、可脱敏、可裁剪、可审计
```

---

## 一、允许做

1. 新增 `agent/communication/`；
2. 新增消息数据类；
3. 新增消息枚举；
4. 新增 MessagePolicy；
5. 新增 MessageSanitizer；
6. 新增 MessageWindow；
7. 新增基础单元测试；
8. 保持旧接口兼容。

---

## 二、禁止做

1. 不接入 executor 主链；
2. 不改 ToolExecutor 默认行为；
3. 不改 Write Gateway；
4. 不改 ContextManager；
5. 不实现完整 MemoryManager；
6. 不实现完整 ReAct；
7. 不实现完整 Reflection；
8. 不实现完整 Multi-Agent；
9. 不大改 UI。

---

## 三、建议新增文件

```text
agent/communication/__init__.py
agent/communication/message_types.py
agent/communication/message_policy.py
agent/communication/message_sanitizer.py
agent/communication/message_window.py
```

---

## 四、核心模型

### 1. AgentMessage

建议字段：

```text
message_id
conversation_id
run_id
task_id
parent_task_id
sender
receiver
message_type
status
priority
created_at
payload
payload_schema
context_refs
artifact_refs
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
可建立 parent-child 链路
可携带 context_id / artifact_ref / approval_ref
不直接携带大型原始对象
```

### 2. MessageEnvelope

建议字段：

```text
envelope_id
message
route
visibility
delivery_status
retry_count
created_at
delivered_at
trace_id
```

### 3. MessageType

至少包含：

```text
USER_REQUEST
CONTEXT_CREATED
GOAL_PARSED
TASK_PLANNED
TOOL_CALL_REQUESTED
TOOL_RESULT_RECEIVED
OBSERVATION_CREATED
APPROVAL_REQUESTED
APPROVAL_RESULT_RECEIVED
ARTIFACT_CREATED
ERROR_RAISED
WARNING_RAISED
REPORT_DRAFTED
FINAL_REPORT
HANDOFF_REQUESTED
REFLECTION_REQUESTED
REFLECTION_RESULT
```

### 4. MessageStatus

```text
CREATED
QUEUED
DELIVERED
CONSUMED
FAILED
SKIPPED
EXPIRED
```

### 5. MessageVisibility

```text
LLM_VISIBLE
TOOL_ONLY
SYSTEM_ONLY
UI_VISIBLE
AUDIT_ONLY
SECRET
```

MessageVisibility 可复用 Phase 12 ContextPolicy 的理念，但不要强耦合。

---

## 五、MessagePolicy

必须实现：

```text
classify_field()
classify_message()
can_deliver()
can_show_to_llm()
can_show_to_ui()
requires_redaction()
```

规则：

```text
confirmation_token -> SECRET
api_key / tushare_token / password / secret -> SECRET
db_path / database_path / local path -> SYSTEM_ONLY
stack_trace / traceback -> AUDIT_ONLY
raw_positions / raw_evidence / full_payload -> TOOL_ONLY
summary / refs / token_present -> LLM_VISIBLE
```

---

## 六、MessageSanitizer

必须实现：

```text
sanitize_for_llm()
sanitize_for_ui()
sanitize_for_tool()
sanitize_for_audit()
```

要求：

```text
LLM 版本不含 secret
UI 版本不含 internal stack/path/token
Tool 版本按 permission 过滤
Audit 版本可保留 trace，但不能保留原始 secret
```

---

## 七、MessageWindow

必须实现：

```text
trim_messages_to_budget()
summarize_old_messages()
keep_required_messages()
estimate_message_size()
```

要求：

```text
USER_REQUEST 保留
FINAL_REPORT 保留
APPROVAL_REQUESTED 摘要保留
TOOL_RESULT_RECEIVED 摘要+artifact_ref 保留
大对象只保留 ref
```

---

## 八、测试

新增：

```text
tests/unit/test_phase13_message_core.py
tests/unit/test_phase13_message_policy.py
```

覆盖：

```text
AgentMessage 可创建
AgentMessage 可序列化
MessageEnvelope 可创建
MessageType 完整
secret 不进入 LLM
confirmation_token 不进入 LLM/UI
DB path 不进入 LLM/UI
stack trace 不进入 LLM/UI
raw payload 只保留 ref
MessageWindow 保留 required messages
```

运行：

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase13_message_core.py -q
py -3 -m pytest tests/unit/test_phase13_message_policy.py -q
py -3 -m pytest tests/unit/test_phase12_context_policy.py -q
py -3 -m pytest tests/unit/test_phase12_context_core.py -q
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
docs/phase13_b_message_core_report.md
```

必须包含：

```text
新增文件
消息模型
消息类型
MessagePolicy 规则
MessageSanitizer 结果
MessageWindow 裁剪规则
测试结果
网页检查结果
NEXT_STAGE_ALLOWED = true / false
```

---

## 十一、验收标准

1. agent/communication 包建立；
2. AgentMessage 建立；
3. MessageEnvelope 建立；
4. MessageType 建立；
5. MessagePolicy 建立；
6. MessageSanitizer 建立；
7. MessageWindow 建立；
8. secret 不进 LLM/UI；
9. 大对象摘要+ref；
10. compileall 通过；
11. 单测通过；
12. 真实网页检查通过；
13. NEXT_STAGE_ALLOWED = true。
