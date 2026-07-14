# Phase 14-A Memory Source Audit Report

## 阶段目标

本阶段只完成记忆来源审计和 MemoryManager 目标协议设计，不接入 Executor / ToolExecutor / ContextManager / MessageBus / WriteGateway / UI，不修改数据库 schema，不写入新的业务状态。

## 新增/修改文件

- 新增：`docs/phase14_a_memory_source_audit_report.md`
- 未新增 `agent/memory/README.md`：当前项目已存在 `agent/memory.py` 单文件旧记忆模块，直接创建同名目录会冲突。该文件已纳入审计，后续阶段需要先最小迁移或兼容包装。

## 当前发现

- 已有旧入口：`agent/memory.py`
  - `LayeredMemoryService`
  - `MemoryProtocolItem`
  - `ScoredMemory`
  - `MemoryWeights`
  - `remember_memory()`
  - `remember_semantic_memory()`
  - `retrieve_layered_memory()`
  - `memory_view_for_agent()`
  - 内置敏感字段脱敏与长期偏好确认规则
- 已有数据库基础：`database/migrations/014_agent_runtime_history.sql`
  - `conversation_summaries`
  - `memory_items`
  - `memory_links`
  - `user_feedback`
  - `artifacts`
- 已有 Repository：`database/repositories/agent_repository.py`
  - `upsert_memory_item()`
  - `get_memory_item()`
  - `update_memory_item()`
  - `list_memory_items()`
  - `upsert_memory_link()`
  - `list_memory_links()`
  - `upsert_user_feedback()`
  - `list_user_feedback()`

## 记忆来源审计表

| memory_source | file | function_or_class | source_type | candidate_memory_type | data_fields | contains_user_preference | contains_event | contains_evidence | contains_portfolio | contains_approval | contains_secret_risk | should_store | store_reason | forbidden_fields | planned_memory_type | migration_phase |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UserProfile | `portfolio/user_profile.py`, `database/repositories/user_repository.py` | `load_user_context`, profile/risk/goal repository methods | profile_setting | SemanticMemory / PortfolioMemory | profile_type, risk_level, constraints, investment_goal | yes | no | no | yes | no | low | yes | 用户长期偏好和风险约束可作为长期记忆，但只保存摘要 | api_key, token, db_path, raw questionnaire path | user_preference / user_profile | B-E |
| ContextBundle / MemoryContext | `agent/context/context_types.py`, `agent/context/context_builder.py` | `ContextBundle`, `MemoryContext`, `ContextManager` | context_snapshot | WorkingMemory | context_id, memory_refs, recent_decision_refs, user_goal, task_plan | partial | yes | partial | partial | partial | medium | partial | 只保存 refs 和摘要，不保存 raw context | raw_positions, raw_evidence, stack_trace, db_path | working_memory_refs | E |
| AgentMessage / MessageTrace | `agent/communication/message_types.py`, `agent/communication/message_store.py` | `AgentMessage`, `MessageStore`, `MessageTrace` | message_trace | EpisodicMemory | message_type, sender, receiver, refs, summaries | partial | yes | yes | partial | yes | medium | yes | 可生成执行 episode，但只保存类型、摘要和 refs | raw payload, confirmation_token, local path, traceback | episodic_memory | E |
| UnifiedToolResult | `agent/tool_engine.py` | `UnifiedToolResult`, `ToolExecutor.execute` | tool_result | EvidenceMemory / PortfolioMemory / EpisodicMemory | success, tool_name, message, data summary, sources, artifact_id | no | yes | yes | yes | partial | high | partial | 工具结果有价值，但必须经 Artifact/summary 化 | raw data, API key, token, db_path, stack trace | tool_result_summary_memory | E |
| Artifact | `agent/artifacts.py` | `Artifact`, `ArtifactStore` | artifact | EvidenceMemory / PortfolioMemory | artifact_id, artifact_type, content_summary, sources | no | yes | yes | yes | partial | medium | yes | Artifact 已有摘要和 ref，适合作为长期记忆来源 | artifact path, raw content, secret keys | artifact_ref_memory | E |
| RuntimeTrace | `agent/runtime.py`, `agent/runtime_reliability.py` | runtime recorder/checkpointer | runtime_event | EpisodicMemory | run_id, status, warnings, errors summary | no | yes | no | no | no | high | partial | 只保存状态摘要和失败类型，避免堆栈泄漏 | stack_trace, file path, db_path | runtime_episode | D-E |
| Portfolio state / risk / proposal | `agent/tools/portfolio_state_tool.py`, `agent/tools/portfolio_risk_tool.py`, `agent/tools/portfolio_proposal_adapters.py`, `portfolio/portfolio_risk.py` | portfolio state/risk/proposal tools | portfolio_snapshot | PortfolioMemory | account summary, position count, risk level, recommendation summary | partial | yes | no | yes | partial | medium | partial | 可保存风险摘要和建议摘要，不保存完整持仓明细作为长期事实 | raw_positions, order preview raw payload, confirmation_token | portfolio_summary_memory | E |
| WriteGateway audit | `agent/write_gateway.py`, `agent/session/confirmation_manager.py` | `execute_confirmed_plan_v2`, `create_confirmation_plan` | approval_event | EpisodicMemory / PortfolioMemory | plan_id, status, operation_type, result summary | no | yes | no | yes | yes | high | yes | 可追踪确认闭环，但只保存 plan_id/status/summary/token_present | confirmation_token, confirmation_token_hash, plan_hash raw, snapshot hash raw | approval_episode | E |
| Pending confirmation plan | `agent/session/pending_action_store.py`, `agent/session/confirmation_manager.py` | pending action/confirmation storage | pending_plan | WorkingMemory | plan_id, operation_type, status, expires_at, summary | no | yes | no | yes | yes | high | partial | 只进 working memory，用于当前会话提醒，不直接进入长期记忆 | confirmation_token, hash, raw changes | working_approval_memory | E |
| News/RAG evidence | `rag/`, `agent/tools/stock_rag_tool.py`, `agent/tools/stock_news_tool.py`, `pipelines/rag_pipeline.py`, `database/repositories/news_repository.py` | retrievers, retrieval log, evidence tools | evidence | EvidenceMemory / SemanticMemory | stock_code, title, source_time, snippet, evidence ids | no | yes | yes | no | no | medium | yes | 可保存证据摘要和 source refs，避免重复检索解释 | raw article text, full chunk body, local index path | evidence_memory | E |
| AI Agent conversation history | `app/pages/ai_agent.py`, `database/repositories/agent_repository.py` | `_persist_conversation_message`, `messages` table | conversation_message | WorkingMemory / EpisodicMemory | role, content, metadata, run_id | yes | yes | partial | partial | partial | high | partial | 最近消息可作 working memory；长期记忆必须由 candidate extractor + policy 筛选 | raw user secrets, confirmation token, API key, DB path | working / candidate episodic | E |
| AI Paper Trading page history | `app/pages/ai_paper_trading.py`, `portfolio/storage.py` | page actions, account/order/risk history | portfolio_history | PortfolioMemory | account snapshots, orders, risk report, cash flow summary | partial | yes | no | yes | partial | medium | partial | 可保存组合变化摘要，不保存每次全量账户对象 | raw account dump, raw order payload, local files | portfolio_event_memory | E |
| 用户反馈 / 纠正 | `database/migrations/014_agent_runtime_history.sql`, `agent/memory.py` | `user_feedback`, `remember_memory` | user_feedback | SemanticMemory / ReflectionMemory placeholder | feedback_type, rating, comment, source_id | yes | yes | no | partial | no | high | yes | 用户明确纠正和偏好是高价值长期记忆，必须脱敏和确认 | secret, token, one-time instruction, unsupported inference | feedback_memory | B-D |

## MemoryRecord 目标字段设计

| 字段 | 说明 |
| --- | --- |
| `memory_id` | 全局唯一 ID |
| `user_id` | 用户隔离主键 |
| `conversation_id` | 可选会话来源 |
| `run_id` | 可选 Agent run 来源 |
| `memory_type` | Working / Episodic / Semantic / Evidence / Portfolio / Reflection placeholder / Perceptual placeholder |
| `content` | 经脱敏后的短文本摘要 |
| `summary` | 面向 LLM/UI 的安全摘要 |
| `topics` | 主题标签 |
| `stock_codes` | 股票代码实体 |
| `source_type` | user_feedback / message_trace / artifact / tool_result / approval_event 等 |
| `source_id` | 来源记录 ID |
| `importance` | 0-1 重要性 |
| `confidence` | 0-1 可信度 |
| `status` | active / superseded / deleted / expired |
| `valid_from` | 生效时间 |
| `valid_until` | 失效时间 |
| `supersedes_memory_id` | 被替代记忆 |
| `metadata` | 仅保存脱敏后的结构化元数据 |

## MemoryType 初步设计

- `working`: 当前会话 / 当前 run / pending plan 的短期记忆。
- `episodic`: 执行事件、MessageTrace、工具调用、审批闭环摘要。
- `semantic`: 用户明确确认的长期偏好、投资目标、稳定约束。
- `evidence`: 新闻、RAG、MCP、报告证据摘要和 source refs。
- `portfolio`: 持仓、风险、建议、回放的摘要化记忆。
- `reflection`: 轻量占位，仅记录未来可接入的评估摘要，不实现完整 Reflection。
- `perceptual`: 轻量占位，不接入多模态存储。

## MemoryPolicy 初步设计

- 长期用户偏好必须来自用户明确表达或确认，不能来自 Agent 推断。
- 一次性操作、临时调仓请求、预览结果不能升级为长期偏好。
- 写操作相关记忆只保存 `plan_id`、`operation_type`、`status`、`token_present`、摘要和 refs。
- raw tool payload、raw positions、raw evidence、raw article、raw traceback 不直接入长期记忆。
- 所有记忆按 `user_id` 隔离。
- MemoryManager 不能直接写模拟盘、策略或资金状态。

## 禁止字段清单

- `confirmation_token`
- `confirmation_token_hash`
- `api_key`
- `llm_api_key`
- `tushare_token`
- `password`
- `secret`
- `authorization`
- `cookie`
- `db_path`
- 本地绝对路径
- `stack_trace`
- `Traceback (most recent call last)`
- raw positions / raw evidence / raw tool payload

## 计划接入点

- Phase B：抽取 `MemoryRecord`、`MemoryType`、`MemoryPolicy`、`MemorySanitizer`；保持 `agent/memory.py` 兼容。
- Phase C：实现 `WorkingMemory`、`SQLiteMemoryStore`、`MemoryRetriever`；复用现有 `memory_items` 表。
- Phase D：实现 `MemoryManager`、`MemoryCandidateExtractor`、`MemoryConsolidator`、`MemoryPruner`。
- Phase E：接入 Context / Message / Tool / UI；MemoryTool 只读；不改变 WriteGateway。
- Phase F：最终覆盖率、安全扫描、网页回归和交付报告。

## 安全过滤结果

- 当前 `agent/memory.py` 已有敏感键过滤，但仍是单文件旧结构，后续需模块化并扩大本地路径 / traceback 过滤。
- 当前 `AgentRepository` 支持 memory 表，不需要阶段 A 改 schema。
- 当前 Artifact / Message / Context 均已有 sanitizer，可作为 MemorySanitizer 的参考和输入防线。

## 测试命令与结果

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts`: PASS
- `py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q`: PASS, 7 passed
- `py -3 -m pytest tests/unit/test_phase12_context_core.py -q`: PASS, 2 passed
- `py -3 -m pytest tests/unit/test_phase13_message_core.py tests/unit/test_phase13_message_store_bus.py -q`: PASS, 6 passed

Warnings:

- `agent/capability_index.py` 仍有既有 `datetime.utcnow()` deprecation warning。

## 真实网页检查结果

- WEB_CHECK_DONE = true
- WEB_CHECK_METHOD = 8501 health + Streamlit AppTest + local Playwright Chromium
- WEB_CHECK_PAGES = 首页 / 预测排名, AI Agent, AI 模拟盘, 系统监控
- WEB_CHECK_RESULT = PASS
- WEB_CHECK_ERRORS = []

Details:

- `http://127.0.0.1:8501/_stcore/health`: `ok`
- `scripts/check_phase13_communication_web.py`: PASS
  - 首页 / 预测排名: exceptions=0, errors=0
  - AI Agent: exceptions=0, errors=0
  - AI 模拟盘: exceptions=0, errors=0
  - 系统监控: exceptions=0, errors=0
- AI Agent clean-user inputs:
  - `查看我的当前持仓`: PASS
  - `分析当前组合风险`: PASS
  - `给我一个调仓建议`: PASS
  - `查看系统状态`: PASS
- Playwright Chromium real navigation:
  - 首页 / 预测排名: marker visible, no traceback, no mojibake, no sensitive field
  - AI 模拟盘: marker visible, no traceback, no mojibake, no sensitive field
  - AI Agent: marker visible, no traceback, no mojibake, no sensitive field
  - 系统监控: marker visible, no traceback, no mojibake, no sensitive field

Known non-blocking warning:

- 系统监控页仍有 Streamlit dataframe Arrow 自动修复 warning，页面检查无异常。

## 失败项

- 无阶段阻塞失败项。

## 未完成项

- 尚未实现模块化 MemoryManager。
- 尚未接入 Executor / Context / Message / Tool / UI。
- 尚未实现 MemoryTool。
- 尚未迁移旧 `agent/memory.py` 到 `agent/memory/` 包结构。

## 决策

NEXT_STAGE_ALLOWED = true
