# 38 Agent Runtime Sandbox Approval Memory Async Traceability

更新时间：2026-06-23

## 阶段目标

本阶段升级现有 AI Agent 通用运行框架，不修改预测模型、模拟盘策略或交易规则。核心能力包括多步骤执行、只读并发、受限 Python 分析、ActionProposal 确认网关、运行历史、来源追踪、长期记忆和用户反馈。

## 实际修改文件

- `agent/schemas.py`
- `agent/orchestration/multi_task_executor.py`
- `agent/session/confirmation_manager.py`
- `agent/tools/tool_registry.py`
- `agent/tools/python_sandbox_tool.py`
- `agent/sandbox.py`
- `agent/tools/rebalance_plan_tool.py`
- `agent/tools/paper_trade_execute_tool.py`
- `agent/tools/capital_management_tool.py`
- `agent/tools/backfill_tool.py`
- `app/pages/ai_agent.py`
- `database/migrations/014_agent_runtime_history.sql`
- `database/table_registry.py`
- `database/repositories/agent_repository.py`
- `PROJECT_STRUCTURE.md`
- `PROJECT_FILE_DIRECTORY.md`
- `database/README.md`
- `docs/handoff/PROJECT_STATUS.md`

## 新增测试

- `tests/unit/test_agent_runtime_contracts.py`
- `tests/unit/test_agent_multi_task_async.py`
- `tests/unit/test_agent_runtime_persistence.py`
- `tests/unit/test_agent_python_sandbox.py`
- `tests/unit/test_agent_action_proposal_gateway.py`
- `tests/unit/test_ai_agent_runtime_ui_helpers.py`

## 新增数据库表

迁移文件：`database/migrations/014_agent_runtime_history.sql`

新增表：

- `conversations`
- `messages`
- `agent_runs`
- `agent_steps`
- `agent_tool_calls`
- `agent_sources`
- `agent_sandbox_runs`
- `action_proposals`
- `action_approvals`
- `action_commits`
- `conversation_summaries`
- `memory_items`
- `memory_links`
- `user_feedback`
- `artifacts`

这些表只保存 Agent 运行元数据，不作为模拟盘账户、现金、持仓、订单或资金流水的正式业务状态。

## Agent 运行流程

```text
用户问题
    -> 分层意图识别
    -> multi_task_executor 构造任务状态
    -> 无依赖只读任务并发执行
    -> 有依赖任务等待前置结果
    -> 必要时调用 python_sandbox_analysis
    -> 聚合回答
    -> 保存工具、来源、步骤和反馈元数据
```

任务状态来自 `AgentTaskStatus`，步骤状态来自 `AgentStepStatus`。审计只保存目标、步骤、工具、参数摘要、观察摘要、错误和重试状态，不保存隐藏思维过程。

## 异步并发边界

实现位置：`agent/orchestration/multi_task_executor.py`

- 只读任务可以并发。
- `preview_add_stock`、`confirm_execute`、`capital_management`、`backfill` 等受保护任务不能进入多任务并发入口。
- 依赖任务按 `depends_on` 分批执行。
- 默认限制：最多 4 个并发读取、单步 30 秒超时、最多 2 次重试。
- 同一账户正式写入仍通过现有确认工具串行执行。

## 工具风险边界

实现位置：`agent/tools/tool_registry.py`

每个工具公开：

- `input_schema`
- `output_schema`
- `read_only`
- `has_side_effect`
- `requires_confirmation`
- `concurrency_safe`
- `idempotent`
- `timeout_seconds`
- `retry_policy`
- `result_retention`
- `category`

修改类和正式执行类工具默认不是只读，不能自动进入并发组。

## Python 沙箱限制

实现位置：

- `agent/sandbox.py`
- `agent/tools/python_sandbox_tool.py`

当前实现是单机项目中的受限分析运行器，不是面向不受信任多租户的硬隔离沙箱。

安全边界：

- 只接收显式传入的 `SNAPSHOT`。
- 先进行 AST 检查。
- 只允许有限 Python 库：`json`、`math`、`statistics`、`datetime`、`collections`、`decimal`、`pandas`、`numpy`、有限 `matplotlib`。
- 禁止 `os`、`subprocess`、`socket`、`requests`、`urllib`、`shutil`、`sqlite3`、`pathlib` 等。
- 禁止 `open`、`eval`、`exec`、`compile`、`input`、`__import__`、`globals`、`locals` 等。
- 禁止 pandas 文件读取和写出方法，如 `read_csv`、`to_csv`。
- 子进程运行在独立临时目录，设置最小环境变量。
- 支持超时终止和 stdout 截断。

沙箱结果只能用于回答和预案生成，不能直接写正式业务表。

## 确认和执行流程

实现位置：`agent/session/confirmation_manager.py`

预案字段：

- `plan_id`
- `user_id`
- `operation_type`
- `snapshot_id`
- `business_state_version`
- `plan_hash`
- `before_state_summary`
- `proposed_changes`
- `after_state_preview`
- `warnings`
- `validation_results`
- `expires_at`

确认规则：

- 预案创建时写入 pending action 文件，并同步写入 `action_proposals`。
- `confirmation_token` 不写入 `action_proposals`。
- 用户必须在页面点击确认并输入令牌。
- 自然语言“好的”“继续”不会触发执行。
- `validate_confirmation()` 会校验 token、过期时间和 `plan_hash`。
- 校验通过后令牌立即一次性消费。
- 方案被篡改会返回 `plan_hash_mismatch`。
- 重复确认会返回 `confirmation_already_used` 或 `already_executed`。
- 纸面交易执行前重新读取当前账户摘要，对比预案的 `before` 摘要，状态变化时拒绝旧方案。
- 正式执行仍调用现有 `run_paper_trading_pipeline(...)`、`add_cash_flow(...)`、`run_paper_trading_backfill(...)`。

## 历史、记忆和检索方案

新增运行表支持：

- 原始会话：`conversations`、`messages`
- 任务历史：`agent_runs`、`agent_steps`
- 工具历史：`agent_tool_calls`
- 来源：`agent_sources`
- 沙箱：`agent_sandbox_runs`
- 预案、确认、提交：`action_proposals`、`action_approvals`、`action_commits`
- 摘要：`conversation_summaries`
- 长期记忆：`memory_items`、`memory_links`
- 反馈：`user_feedback`
- 大型产物索引：`artifacts`

本阶段提供 SQLite 表和 repository 封装。历史混合检索应复用现有 `rag/` 的 BM25、dense、hybrid、reranker 能力继续扩展，不另建第二套检索框架。

## 前端展示

实现位置：`app/pages/ai_agent.py`

新增展示：

- 多任务步骤表
- 并发读取批次
- 工具调用表
- 来源摘要
- Python 沙箱摘要
- 工具元数据表
- 方案 hash、snapshot、state version 和前后差异
- 取消方案按钮
- 用户反馈入口

前端仍不展示隐藏思维过程。

## 生命周期和清理

当前已有：

- 沙箱临时目录任务结束后自动删除。
- 过期方案不可确认。
- 取消方案只改变方案状态，不改正式业务状态。
- 大型产物只在 `artifacts` 存路径、hash、大小和保留策略。

后续建议：

- 增加用户级历史删除入口，并同步删除摘要、记忆和索引。
- 增加定期清理过期预案、低价值临时记录和旧检索缓存的任务。

## 已执行验证

- 阶段 A：`13 passed in 10.68s`
- 阶段 B：`8 passed in 14.92s`
- 阶段 C：`10 passed in 6.16s`
- 阶段 D：`11 passed in 11.66s`
- 阶段 E：`8 passed in 16.39s`
- 阶段 F 局部：`7 passed in 13.89s`

覆盖点：

- 工具元数据和参数校验
- 受保护写入边界
- 只读并发和依赖顺序
- protected multi-intent 拒绝
- 数据库迁移和 repository round trip
- 用户隔离
- Python 沙箱正常执行、安全拒绝、超时和输出截断
- ActionProposal 持久化、plan_hash、防篡改和一次性确认
- AI Agent 页面 traceability helper

## 已知限制

- 沙箱不是 Docker/VM 级强隔离，只适用于本地单机项目受限分析。
- 历史检索表和 repository 已有，但长对话自动摘要、向量索引同步删除和 Recall/MRR/nDCG 评估还需后续扩展。
- 前端反馈已写入 `user_feedback`，统计看板仍需后续补。
- 当前 Agent 不会自动创建生产工具，只记录反馈和工具失败。
- 本阶段不修改 Top10/Top15、仓位分配、新闻调整、用户适配或模拟盘成交规则。

## 本地验证命令

```powershell
py -m pytest tests/unit/test_agent_runtime_contracts.py tests/unit/test_agent_multi_task_async.py tests/unit/test_agent_runtime_persistence.py tests/unit/test_agent_python_sandbox.py tests/unit/test_agent_action_proposal_gateway.py tests/unit/test_ai_agent_runtime_ui_helpers.py -q
py -m pytest tests/unit/test_agent_write_requires_confirmation.py tests/unit/test_agent_idempotency.py tests/unit/test_agent_paper_trade_execution.py tests/unit/test_agent_capital_management_tool.py tests/unit/test_agent_user_isolation.py -q
streamlit run app.py --server.port 8501 --server.address 127.0.0.1
```

## 合规声明

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。Agent 只操作项目内模拟盘和运行元数据，不连接真实券商，不提交真实订单。
