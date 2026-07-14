# Phase 12-B：Context 核心模型、Policy、Sanitizer、Window

## 本阶段目标

建立上下文系统的核心数据结构和安全策略，但暂不深度接入主执行链。

目标：

```text
新增 agent/context/
新增 ContextBundle 和各类 Context 数据结构
新增 ContextPolicy
新增 ContextSanitizer
新增 ContextWindow
保证上下文可序列化、可裁剪、可脱敏
```

---

## 一、允许做

1. 新增 `agent/context/`；
2. 新增 context 数据类；
3. 新增 ContextPolicy；
4. 新增 ContextSanitizer；
5. 新增 ContextWindow；
6. 新增基础单元测试；
7. 保持旧接口兼容。

---

## 二、禁止做

1. 不接入 executor 主链；
2. 不改 ToolExecutor 默认行为；
3. 不改 Write Gateway；
4. 不实现完整 MemoryManager；
5. 不实现 MessageBus；
6. 不让上下文系统直接读写业务数据库；
7. 不大改 UI。

---

## 三、建议新增文件

```text
agent/context/__init__.py
agent/context/context_types.py
agent/context/context_policy.py
agent/context/context_sanitizer.py
agent/context/context_window.py
```

---

## 四、ContextBundle 字段

至少包含：

```text
context_id
user_id
conversation_id
run_id
task_id
created_at
updated_at
locale
user_context
conversation_context
task_context
tool_context
portfolio_context
evidence_context
artifact_context
approval_context
runtime_context
memory_context
visibility_policy
token_budget
metadata
```

---

## 五、上下文类型

必须实现：

```text
UserContext
ConversationContext
TaskContext
ToolContext
PortfolioContext
EvidenceContext
ArtifactContext
ApprovalContext
RuntimeContext
MemoryContext
```

MemoryContext 只做轻量占位：

```text
memory_refs
user_preference_refs
recent_decision_refs
```

不得实现 embedding memory。

---

## 六、ContextPolicy

必须支持：

```text
LLM_VISIBLE
TOOL_ONLY
SYSTEM_ONLY
UI_VISIBLE
AUDIT_ONLY
SECRET
```

必须有规则：

```text
confirmation_token 原文 SECRET
API key SECRET
DB path SYSTEM_ONLY 或 SECRET
内部堆栈 SYSTEM_ONLY / AUDIT_ONLY
完整 portfolio 大对象 TOOL_ONLY
完整 evidence 大对象 TOOL_ONLY
portfolio summary LLM_VISIBLE
evidence summary LLM_VISIBLE
artifact_ref LLM_VISIBLE
```

---

## 七、ContextSanitizer

必须实现：

```text
sanitize_for_llm()
sanitize_for_tool()
sanitize_for_ui()
sanitize_for_audit()
```

要求：

```text
LLM 版本不包含 secret
UI 版本不包含内部堆栈
Tool 版本按 permission_scope 过滤
Audit 版本可保留 trace，但不可保留原始 secret
```

---

## 八、ContextWindow

必须实现：

```text
trim_to_budget()
summarize_old_context()
keep_required_refs()
estimate_context_size()
```

规则：

```text
最新用户请求必须保留
UserGoal / TaskPlan 必须保留
pending approval 摘要必须保留
artifact_ref 必须保留
大型 portfolio/evidence 只保留摘要+ref
```

---

## 九、测试

新增：

```text
tests/unit/test_phase12_context_core.py
tests/unit/test_phase12_context_policy.py
```

覆盖：

```text
ContextBundle 可创建
ContextBundle 可序列化
各 Context 类型可创建
secret 不进入 LLM
confirmation_token 不进入 LLM
portfolio 大对象裁剪为摘要+ref
evidence 大对象裁剪为摘要+ref
UI sanitized 不含内部堆栈
trim_to_budget 保留 required refs
```

运行：

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase12_context_core.py -q
py -3 -m pytest tests/unit/test_phase12_context_policy.py -q
py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q
py -3 -m pytest tests/unit/test_phase10_goal_planning.py -q
py -3 -m pytest tests/unit/test_phase10_3_capability_artifacts.py -q
```

---

## 十、真实网页检查

检查：

```text
http://127.0.0.1:8501/_stcore/health
首页
AI Agent 页面
AI 模拟盘页面
系统监控页面
```

因为本阶段未接入主链，页面行为应保持不变。

---

## 十一、阶段报告

生成：

```text
docs/phase12_b_context_core_report.md
```

必须包含：

```text
新增文件
Context 数据结构
Policy 规则
Sanitizer 结果
Window 裁剪规则
测试结果
网页检查结果
NEXT_STAGE_ALLOWED = true / false
```

---

## 十二、验收标准

1. agent/context 包建立；
2. ContextBundle 建立；
3. 10 类 Context 建立；
4. ContextPolicy 建立；
5. ContextSanitizer 建立；
6. ContextWindow 建立；
7. secret 不进 LLM；
8. 大对象摘要+ref；
9. compileall 通过；
10. 单测通过；
11. 真实网页检查通过；
12. NEXT_STAGE_ALLOWED = true。
