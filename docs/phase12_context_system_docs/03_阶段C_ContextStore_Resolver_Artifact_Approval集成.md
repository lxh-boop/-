# Phase 12-C：ContextStore、ContextResolver、Artifact 与 Approval 集成

## 本阶段目标

在核心模型基础上，建立上下文存储、引用解析，并接入 Artifact 与 Approval 的上下文引用。

目标：

```text
ContextStore
ContextResolver
ArtifactContext 集成
ApprovalContext 集成
pending plan 上下文摘要
artifact_ref 解析
```

---

## 一、允许做

1. 新增 ContextStore；
2. 新增 ContextResolver；
3. 接入 ArtifactStore 只读引用；
4. 接入 confirmation_manager / Write Gateway 只读摘要；
5. 增加上下文 snapshot；
6. 增加单测。

---

## 二、禁止做

1. 不改变 Write Gateway 的审批逻辑；
2. 不改变 Artifact 存储语义；
3. 不暴露 confirmation_token 原文；
4. 不实现完整 MemoryManager；
5. 不改 UI 主流程；
6. 不改业务写操作。

---

## 三、建议新增文件

```text
agent/context/context_store.py
agent/context/context_resolver.py
agent/context/context_builder.py
```

如已有 ContextBuilder 草案，可在本阶段完善基础能力。

---

## 四、ContextStore

必须支持：

```text
save_context_snapshot()
load_context_snapshot()
append_tool_result()
append_artifact_ref()
append_runtime_event()
expire_context()
```

存储方式：

```text
优先复用现有 artifact/runtime 存储
可以先用文件或轻量 SQLite
不强制新增复杂 schema
如需 schema 变更，必须最小化并写入报告
```

索引：

```text
context_id
conversation_id
run_id
task_id
```

---

## 五、ContextResolver

必须支持：

```text
resolve_artifact_ref()
resolve_previous_tool_result()
resolve_pending_plan()
resolve_current_portfolio_ref()
resolve_evidence_refs()
resolve_user_preference_ref()
```

本阶段只做结构化解析，不做复杂 LLM 推理。

---

## 六、ArtifactContext 集成

要求：

```text
工具结果 artifact_id / artifact_ref 可进入 ArtifactContext
ArtifactContext 不保存大对象全文
后续任务通过 ref 引用
支持 artifact 过期检查
支持 artifact lineage
```

---

## 七、ApprovalContext 集成

要求：

```text
pending_plan_id
approval_status
plan_hash
expires_at
revalidate_required
confirmation_token_status
```

禁止：

```text
confirmation_token 原文进入 LLM context
confirmation_token 原文进入 UI context
```

LLM 只能看到：

```text
有一个待确认方案
方案类型
方案摘要
是否需要用户确认
是否过期
```

---

## 八、测试

新增：

```text
tests/unit/test_phase12_context_store_resolver.py
tests/unit/test_phase12_context_artifact_approval.py
```

覆盖：

```text
save/load context snapshot
append artifact ref
resolve artifact ref
resolve previous tool result
resolve pending plan
pending plan 不泄露 token
ArtifactContext 不保存大对象全文
ApprovalContext 与 Write Gateway 兼容
```

运行：

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase12_context_store_resolver.py -q
py -3 -m pytest tests/unit/test_phase12_context_artifact_approval.py -q
py -3 -m pytest tests/unit/test_phase12_context_core.py -q
py -3 -m pytest tests/unit/test_phase12_context_policy.py -q
py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q
py -3 -m pytest tests/unit/test_agent_write_requires_confirmation.py -q
py -3 -m pytest tests/unit/test_agent_action_proposal_gateway.py -q
```

---

## 九、真实网页检查

检查：

```text
http://127.0.0.1:8501/_stcore/health
首页
AI Agent 页面
AI Agent 待确认方案区域
AI 模拟盘页面
系统监控页面
```

重点确认：

```text
待确认方案仍可展示
确认 token 不在页面明文显示
页面不报错
```

---

## 十、阶段报告

生成：

```text
docs/phase12_c_context_store_resolver_report.md
```

必须包含：

```text
ContextStore 存储方式
ContextResolver 支持能力
ArtifactContext 集成结果
ApprovalContext 集成结果
安全过滤结果
测试结果
真实网页检查结果
NEXT_STAGE_ALLOWED = true / false
```

---

## 十一、验收标准

1. ContextStore 建立；
2. ContextResolver 建立；
3. ContextBuilder 初步建立；
4. ArtifactContext 可引用 artifact；
5. ApprovalContext 可引用 pending plan；
6. confirmation_token 不泄露；
7. Write Gateway 兼容；
8. 测试通过；
9. 真实网页检查通过；
10. NEXT_STAGE_ALLOWED = true。
