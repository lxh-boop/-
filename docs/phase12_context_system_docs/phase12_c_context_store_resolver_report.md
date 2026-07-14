# Phase 12-C ContextStore / Resolver / Artifact / Approval Report

## 阶段目标

建立上下文快照存储、引用解析，以及 ArtifactContext / ApprovalContext 的安全摘要接入。本阶段不改变 Write Gateway 审批逻辑，不改变 Artifact 存储语义，不新增数据库 schema，不修改业务写操作。

## 修改前状态

| 模块 | 修改前 | 本阶段处理 |
| --- | --- | --- |
| Context snapshot | 不存在统一快照存储 | 新增文件型 `ContextStore` |
| Artifact 引用 | `ArtifactStore` 可保存/读取完整 artifact | 新增 `ContextResolver.resolve_artifact_ref()`，只返回 summary/ref/lineage |
| Pending plan | pending plan 存储含 `confirmation_token` | 新增安全 `ApprovalContext`，只暴露 token_present/status/plan_hash/summary |
| ContextManager | 不存在统一入口 | 新增基础 `ContextManager`，暂不接入 executor 主链 |

## 新增/修改文件

| 文件 | 类型 | 目的 |
| --- | --- | --- |
| `agent/context/context_store.py` | 新增 | 文件型 context snapshot 存储 |
| `agent/context/context_resolver.py` | 新增 | Artifact、pending plan、tool result、refs 解析 |
| `agent/context/context_builder.py` | 新增 | `ContextManager` 基础入口 |
| `agent/context/__init__.py` | 修改 | 导出 `ContextStore`、`ContextResolver`、`ContextManager` |
| `agent/context/context_policy.py` | 修改 | 修正 `confirmation_token_status` 过度脱敏问题 |
| `agent/context/context_builder.py` | 修改 | `ToolContext` 不再保存完整 tool result 到 LLM 可见 metadata |
| `tests/unit/test_phase12_context_store_resolver.py` | 新增 | ContextStore / Resolver 测试 |
| `tests/unit/test_phase12_context_artifact_approval.py` | 新增 | ArtifactContext / ApprovalContext 安全测试 |

## ContextStore 存储方式

- 存储路径：`<output_dir>/context_snapshots/<user_id>/<context_id>.json`
- 保存前使用 `ContextSanitizer.sanitize_for_audit()`，secret 会被替换为 `***`
- 不新增数据库 schema
- 索引字段来自 snapshot 内容：`context_id`、`conversation_id`、`run_id`、`task_id`

已支持：

- `save_context_snapshot()`
- `load_context_snapshot()`
- `append_tool_result()`
- `append_artifact_ref()`
- `append_runtime_event()`
- `expire_context()`

## ContextResolver 支持能力

已支持：

- `resolve_artifact_ref()`
- `resolve_previous_tool_result()`
- `resolve_pending_plan()`
- `resolve_current_portfolio_ref()`
- `resolve_evidence_refs()`
- `resolve_user_preference_ref()`
- `artifact_context_from_refs()`
- `approval_context_from_plan()`

本阶段 resolver 只做结构化解析，不做 LLM 推理。

## ArtifactContext 集成结果

- ArtifactContext 只保存 `artifact_id`、`artifact_type`、`producer_id`、`produced_outputs`、过期状态等引用摘要。
- 不保存 artifact 完整 `content.result` 大对象。
- `resolve_artifact_ref()` 支持过期检查和 lineage：`conversation_id`、`run_id`、`task_id`。
- LLM view 只能看到 artifact summary/ref，不包含文件路径或完整 payload。

## ApprovalContext 集成结果

ApprovalContext 暴露：

- `pending_plan_id`
- `status`
- `plan_hash`
- `expires_at`
- `revalidate_required`
- `confirmation_token_status`
- `token_present`
- `requires_confirmation`
- safe plan summary

禁止并已测试：

- `confirmation_token` 原文不进入 resolver 返回
- `confirmation_token_hash` 不进入 resolver 返回
- `confirmation_token` 原文不进入 LLM context
- UI 检查未发现 `confirmation_token` 明文

Write Gateway 兼容性：

- 本阶段只读 pending plan，不修改 pending plan。
- `get_pending_plan()` 中的原始 pending plan 仍保持原有字段，P0 Write Gateway 回归通过。

## 安全过滤结果

| 字段 | 结果 |
| --- | --- |
| `confirmation_token` | secret，LLM/UI 不可见，audit redacted |
| `confirmation_token_hash` | secret，LLM/UI 不可见 |
| `confirmation_token_status` | safe status，可见 |
| `db_path` / path | LLM 不可见 |
| Artifact path | 不进入 ArtifactContext summary |
| full tool result | 不进入 LLM metadata，只保留 result summary/ref |

## 测试命令与结果

| 命令 | 结果 |
| --- | --- |
| `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts` | pass |
| `py -3 -m pytest tests/unit/test_phase12_context_store_resolver.py -q` | 2 passed |
| `py -3 -m pytest tests/unit/test_phase12_context_artifact_approval.py -q` | 3 passed |
| `py -3 -m pytest tests/unit/test_phase12_context_core.py -q` | 2 passed |
| `py -3 -m pytest tests/unit/test_phase12_context_policy.py -q` | 4 passed |
| `py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q` | 6 passed |
| `py -3 -m pytest tests/unit/test_agent_write_requires_confirmation.py -q` | 1 passed |
| `py -3 -m pytest tests/unit/test_agent_action_proposal_gateway.py -q` | 3 passed |
| `py -3 -m pytest tests/unit/test_multi_agent_phase3_human_approval.py -q` | 5 passed |
| `py -3 -m pytest tests/unit/test_phase10_goal_planning.py -q` | 13 passed |
| `py -3 -m pytest tests/unit/test_phase10_3_capability_artifacts.py -q` | 9 passed |
| `py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q` | 7 passed |

Known warnings: existing `datetime.utcnow()` deprecation warnings in `agent/capability_index.py`.

## 真实网页检查

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = playwright

WEB_CHECK_PAGES = [`http://127.0.0.1:8501/_stcore/health`, `首页 / 预测排名`, `AI Agent`, `AI Agent 待确认方案区域`, `AI 模拟盘`, `系统监控`]

WEB_CHECK_RESULT = pass

WEB_CHECK_ERRORS = []

检查摘要：

| 页面 | 关键功能 | 结果 |
| --- | --- | --- |
| health | `_stcore/health` -> `ok` | pass |
| 首页 / 预测排名 | 标题、模型库管理、手动生成预测排名、每日更新并生成预测排名 | pass |
| AI Agent | 控制中心、清空对话、快捷提问；未发现 `confirmation_token` 明文 | pass |
| AI 模拟盘 | 更新入口、用户与账户摘要、持仓、风险；未发现 `confirmation_token` 明文 | pass |
| 系统监控 | 总状态、保存监控快照、Runtime Reliability；未发现 `confirmation_token` 明文 | pass |

未发现：Traceback、ModuleNotFoundError、NameError、KeyError、Unhandled exception、页面乱码。

## 失败项

无。

## 未完成项

- 尚未将 ContextManager 接入 executor / ToolExecutor 默认执行路径。
- 尚未将 UserGoal / TaskPlan 从 ContextBundle 读取。
- 尚未在 UI 展示 context 安全摘要。

这些内容按阶段 D-E 执行。

NEXT_STAGE_ALLOWED = true
