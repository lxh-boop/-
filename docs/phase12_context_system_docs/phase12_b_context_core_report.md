# Phase 12-B Context Core Report

## 阶段目标

建立 Phase 12 上下文系统核心数据结构与安全策略，但不接入 executor 主链，不修改 ToolExecutor 默认行为，不修改 Write Gateway，不实现完整 MemoryManager，不实现 MessageBus。

## 修改前状态

| 模块 | 修改前 | 本阶段处理 |
| --- | --- | --- |
| `agent/context/schemas.py` | 仅有早期 `BuiltAgentContext`、`ContextItem`、压缩预算 | 保留兼容，不破坏旧 builder |
| `agent/context/builder.py` | 输出 `compressed_text` minimal context | 暂不改主行为 |
| ContextBundle | 不存在 | 新增分层 `ContextBundle` |
| ContextPolicy | 不存在 | 新增可见性策略 |
| ContextSanitizer | 分散在 artifact/runtime 中 | 新增统一 sanitizer |
| ContextWindow | 只有旧 compressor | 新增 bundle 级窗口裁剪 |

## 新增/修改文件

| 文件 | 类型 | 目的 |
| --- | --- | --- |
| `agent/context/context_types.py` | 新增 | 定义 `ContextBundle` 和 10 类 Context |
| `agent/context/context_policy.py` | 新增 | 定义 `LLM_VISIBLE`、`TOOL_ONLY`、`SYSTEM_ONLY`、`UI_VISIBLE`、`AUDIT_ONLY`、`SECRET` |
| `agent/context/context_sanitizer.py` | 新增 | 提供 LLM/Tool/UI/Audit 四种安全视图 |
| `agent/context/context_window.py` | 新增 | 提供上下文估算、裁剪、摘要、required refs 保留 |
| `agent/context/__init__.py` | 修改 | 导出新核心模型，同时保留旧 `build_agent_context` |
| `tests/unit/test_phase12_context_core.py` | 新增 | 验证 Bundle、序列化、窗口裁剪、required refs |
| `tests/unit/test_phase12_context_policy.py` | 新增 | 验证策略与脱敏边界 |

## Context 数据结构

已建立：

- `ContextBundle`
- `UserContext`
- `ConversationContext`
- `TaskContext`
- `ToolContext`
- `PortfolioContext`
- `EvidenceContext`
- `ArtifactContext`
- `ApprovalContext`
- `RuntimeContext`
- `MemoryContext`

`MemoryContext` 仅包含 `memory_refs`、`user_preference_refs`、`recent_decision_refs`，未实现 embedding memory 或长期 MemoryManager。

## Policy 规则

已实现：

- `confirmation_token`、`confirmation_token_hash`、`api_key`、`llm_api_key`、`tushare_token`、`password`、`secret` -> `SECRET`
- `db_path`、`database_path`、`output_dir`、内部路径 -> `SYSTEM_ONLY`
- `stack_trace`、`traceback`、内部堆栈 -> `AUDIT_ONLY`
- `raw_positions`、`raw_evidence`、`full_result` -> `TOOL_ONLY`
- `portfolio summary`、`evidence summary`、`artifact_refs`、`pending_plan_id`、`plan_hash`、`token_present` -> `LLM_VISIBLE`

## Sanitizer 结果

| 视图 | 行为 |
| --- | --- |
| LLM | 移除 secret、数据库路径、内部堆栈；保留 summary/ref/token_present |
| Tool | 保留 tool-only 大对象；默认不暴露 secret；system/write scope 可见 system-only 字段 |
| UI | 移除 secret 和内部堆栈 |
| Audit | 保留 trace 类字段，但 secret 统一替换为 `***` |

## Window 裁剪规则

已实现：

- `trim_to_budget()`
- `summarize_old_context()`
- `keep_required_refs()`
- `estimate_context_size()`

裁剪策略：

- 先把大型 `raw_positions` / `raw_evidence` 转为 `count + refs`，再按目标视图脱敏。
- 保留 latest user request、`user_goal`、`task_plan`、pending approval 摘要、artifact refs。
- 对过长 conversation history 只保留最近消息，并记录 dropped count。

## 测试命令与结果

| 命令 | 结果 |
| --- | --- |
| `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts` | pass |
| `py -3 -m pytest tests/unit/test_phase12_context_core.py -q` | 2 passed |
| `py -3 -m pytest tests/unit/test_phase12_context_policy.py -q` | 4 passed |
| `py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q` | 7 passed |
| `py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q` | 6 passed |
| `py -3 -m pytest tests/unit/test_phase10_goal_planning.py -q` | 13 passed |
| `py -3 -m pytest tests/unit/test_phase10_3_capability_artifacts.py -q` | 9 passed |

Known warnings: existing `datetime.utcnow()` deprecation warnings in `agent/capability_index.py`.

## 真实网页检查

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = playwright

WEB_CHECK_PAGES = [`http://127.0.0.1:8501/_stcore/health`, `首页 / 预测排名`, `AI Agent`, `AI 模拟盘`, `系统监控`]

WEB_CHECK_RESULT = pass

WEB_CHECK_ERRORS = []

检查摘要：

| 页面 | 关键功能 | 结果 |
| --- | --- | --- |
| health | `_stcore/health` -> `ok` | pass |
| 首页 / 预测排名 | 标题、模型库管理、手动生成预测排名、每日更新并生成预测排名 | pass |
| AI Agent | 控制中心、清空对话、快捷提问 | pass |
| AI 模拟盘 | 更新入口、用户与账户摘要、持仓、资金、风险、订单 | pass |
| 系统监控 | 总状态、保存监控快照、Runtime Reliability | pass |

未发现：Traceback、ModuleNotFoundError、NameError、KeyError、Unhandled exception、页面乱码。

## 失败项

无。

## 未完成项

- 尚未接入 `ContextStore` / `ContextResolver`。
- 尚未把 ToolExecutor / Executor 改为消费 ContextBundle。
- 尚未做 UI 层上下文安全视图展示。

这些内容按阶段 C-F 执行。

NEXT_STAGE_ALLOWED = true
