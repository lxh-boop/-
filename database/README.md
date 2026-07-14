# Database Foundation

`database/` 是金融 Agent 的 SQLite 数据底座。第一版默认数据库路径：

```text
data/agent_quant.db
```

本模块围绕四个核心问题建表和封装 repository：

- 用户是否适合
- 模型预测是否可靠
- 新闻事件是否带来风险
- Agent 修改是否有效

## 边界

- 第一版只使用 SQLite。
- 不连接 PostgreSQL、pgvector、Milvus 或 Qdrant。
- 不执行真实交易。
- 不把 RAG 检索分数当作投资信号。
- Agent 不重新预测涨跌，只基于 `model_prediction` 做后处理。

## 初始化

```python
from database import initialize_database

initialize_database()  # 默认 data/agent_quant.db
```

也可以传入测试路径：

```python
initialize_database("tmp/agent_quant_test.db")
```

## 重点表

第一版重点实现：

- `risk_assessment`
- `portfolio_position`
- `model_prediction`
- `news_event`
- `news_chunk`
- `news_stock_mapping`
- `agent_rule`
- `agent_decision_log`
- `backtest_evaluation`
- `rag_retrieval_log`

完整预留表见 `migrations/001_initial_schema.sql`。

第 38 阶段新增 Agent 运行时元数据表，见 `migrations/014_agent_runtime_history.sql`：

- `conversations`、`messages`
- `agent_runs`、`agent_steps`、`agent_tool_calls`
- `agent_sources`、`agent_sandbox_runs`
- `action_proposals`、`action_approvals`、`action_commits`
- `conversation_summaries`
- `memory_items`、`memory_links`
- `user_feedback`
- `artifacts`

这些表只保存对话、任务、工具、来源、沙箱、预案、确认、执行提交、摘要、记忆、反馈和大文件索引等运行元数据。它们不能被模拟盘交易逻辑当作正式账户、现金、持仓或订单状态直接使用。

## Phase 0/1 Schema Note

News content-level support is provided by `database/migrations/016_news_content_level.sql`, which adds `content_level` to both `news_event` and `news_chunk`. Phase 1 did not add a new migration; it reuses the existing migration and writes diagnostic statistics outside the core business tables.

## Phase 2 System Monitoring Tables

Unified monitoring support is provided by `database/migrations/017_system_monitor.sql`:

- `system_monitor_snapshots`
- `system_monitor_alerts`

These tables store observation-only metrics and alerts for data, model, RAG, Agent, and portfolio layers. They must not be used as account, cash, order, position, strategy, or execution state.

The repository is:

```python
from database.repositories import SystemMonitorRepository
```

`SystemMonitorRepository` JSON-encodes metric groups and supports idempotent snapshot and alert upserts. Same user and trade date currently map to a stable snapshot id such as `system_monitor_cht_20260701`.

## Phase 4 Layered Memory

Layered memory does not add a new migration. It reuses:

- `conversations`
- `messages`
- `conversation_summaries`
- `memory_items`
- `memory_links`
- `action_proposals`
- `agent_runs`

The service is:

```python
from agent.memory import LayeredMemoryService
```

`LayeredMemoryService` provides Working/Episodic/Semantic retrieval, user isolation, source traceability, expiry, soft delete, and user-correction supersession. Semantic writes require a user source and source id; one-time operations and Agent inference are rejected as long-term user facts.

## Phase 6 SQLite Lock Retry

No migration is required. `database/sqlite_store.py` retries transient SQLite `database is locked` / `database is busy` errors for basic insert, upsert, get, list, and update operations using short exponential backoff. This is runtime reliability only and does not change schemas or business rules.

## Repository

```python
from database.repositories import AgentRepository, NewsRepository

news_repo = NewsRepository("data/agent_quant.db")
agent_repo = AgentRepository("data/agent_quant.db")
```

每个 repository 支持基础 insert/get/list/update；JSON 字段会在 repository 层做简单编码和解码。

`AgentRepository` 还提供第 38 阶段运行时方法，如：

- `upsert_conversation(...)` / `list_conversations(...)`
- `upsert_message(...)` / `list_messages(...)`
- `upsert_agent_run(...)` / `upsert_agent_step(...)`
- `upsert_agent_tool_call(...)` / `upsert_agent_source(...)`
- `upsert_agent_sandbox_run(...)`
- `upsert_action_proposal(...)` / `get_action_proposal(...)`
- `upsert_action_approval(...)` / `upsert_action_commit(...)`
- `upsert_conversation_summary(...)`
- `list_conversation_summaries(...)`
- `upsert_memory_item(...)` / `get_memory_item(...)` / `update_memory_item(...)` / `list_memory_items(...)`
- `upsert_memory_link(...)` / `list_memory_links(...)`
- `upsert_user_feedback(...)` / `list_user_feedback(...)`
- `upsert_artifact(...)`

## 合规声明

本项目仅用于机器学习研究、金融数据分析、量化策略验证、模拟盘展示和项目作品集展示。不构成投资建议。不承诺收益。不用于实盘自动交易。
