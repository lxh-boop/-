# Phase 11.1-A Tool Inventory Audit Report

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

审计时间：2026-07-04  
审计范围：只读扫描 `agent/`、`app/`、`portfolio/`、`pipelines/`、`rag/`、`database/`、`scripts/` 中与 Agent 工具、Runtime、能力索引、MCP、审批、Artifact、UI 直调相关的代码。  
本轮约束：未修改业务逻辑；未新增工具包装；未迁移工具；未安装新框架；仅新增本审计报告文件。

## 1. 总体结论

当前项目已经存在两套工具体系：

1. 旧版 `ToolSpec` 注册表：`agent/tools/tool_registry.py:get_tool_registry()`，共 26 个工具规格。
2. 新版 `ToolDefinition` + `ToolExecutor`：`agent/tool_engine.py:build_core_tool_definitions()`，共 8 个核心读/系统工具。

真实主链路是混合状态：

- 核心只读工具中，8 个已进入新版 `ToolDefinition`，并可通过 `ToolExecutor` 返回 `UnifiedToolResult`。
- 多任务执行器对这 8 个工具优先使用新版注册表，但写操作、部分读工具、MCP、Python sandbox、策略、资金、回填、确认执行仍大量走旧函数直调。
- 能力索引已经接入 v2 与旧工具，但它是“能力视图”，不是统一执行入口。`agent/capability_index.py:build_trusted_capability_index()` 当前生成 23 条能力记录。
- Artifact 持久化只在新版 `ToolExecutor` 路径自动保存；多任务执行器有同轮 in-memory cache，但没有把持久 artifact 作为统一复用入口。
- 写操作大多具备确认、重新校验和提交记录，但存在 P0 级绕过点：策略禁用直写、AI 模拟盘页面资金/回填直调、Agent 页面确认按钮绕过 `ToolExecutor`。

### 关键统计

| 口径 | 数量 | 说明 |
| --- | ---: | --- |
| 旧版 `ToolSpec` 注册工具 | 26 | `agent/tools/tool_registry.py:get_tool_registry()` |
| 新版 `ToolDefinition` 注册工具 | 8 | `agent/tool_engine.py:build_core_tool_definitions()` |
| 能力索引记录 | 23 | `agent/capability_index.py:build_trusted_capability_index()` |
| v2 已适配 legacy name | 8 | `portfolio_state`、`portfolio_risk`、`ranking`、`stock_analysis`、`stock_news`、`stock_rag`、`scheduler_status`、`report` |
| 严格走 `ToolExecutor` 默认路径 | 8 | 多任务读工具优先 v2；旧 AgentCore、写操作、UI 直调不算 |
| 返回 `UnifiedToolResult` | 8 | 仅新版执行器路径 |
| 自动持久化 artifact | 8 | 仅 `ToolExecutor.execute()` 且 context 有 `db_path` 或 `output_dir` |
| 旧注册表中 requires_confirmation=True | 13 | 包含 preview/write 类工具 |
| 审计发现的可触达工具/服务入口扩展口径 | 41 | 26 个旧 ToolSpec + 9 个 AgentCore 旧 dispatch 入口 + 2 个 MCP 示例发现入口 + 4 个 UI/服务型直调入口 |

扩展口径覆盖率：

| 能力 | 覆盖数 | 覆盖率 | 备注 |
| --- | ---: | ---: | --- |
| 新版 `ToolDefinition` | 8/41 | 19.5% | 只读/系统核心工具 |
| 新版 `ToolExecutor` | 8/41 | 19.5% | 写工具尚未迁移 |
| `UnifiedToolResult` | 8/41 | 19.5% | 旧 `ToolResult`/dict 仍大量存在 |
| 自动 artifact 持久化 | 8/41 | 19.5% | 旧执行器多为内存缓存或无 artifact |
| Runtime policy 严格经 `ToolExecutor` | 8/41 | 19.5% | 旧链路中部分调用 `execute_with_policy()`，但非统一执行入口 |
| 注册写/预览工具审批声明 | 13/13 | 100% 声明覆盖 | 声明存在，但实际执行存在绕过点 |
| 注册写/预览工具真实审批闭环 | 12/13 | 92.3% | `strategy_management_tool.manage_strategy(action="disable")` 是例外 |

## 2. 新版工具清单

来源：`agent/tool_engine.py:480-609`。

| canonical tool | legacy name | operation | allowed agents | handler | Executor | Unified result | Artifact | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `portfolio.get_state` | `portfolio_state` | read | `main_agent`,`read_worker` | `_portfolio_state_handler()` | 是 | 是 | 是 | 查询模拟盘账户、持仓、订单 |
| `portfolio.analyze_risk` | `portfolio_risk` | read | `main_agent`,`read_worker` | `_portfolio_risk_handler()` | 是 | 是 | 是 | 查询/计算组合风险 |
| `market.get_ranking` | `ranking` | read | `main_agent`,`read_worker` | `_ranking_handler()` | 是 | 是 | 是 | 查询最新 ranking |
| `market.analyze_stock` | `stock_analysis` | read | `main_agent`,`read_worker` | `_stock_analysis_handler()` | 是 | 是 | 是 | 个股综合分析 |
| `market.get_stock_news` | `stock_news` | read | `main_agent`,`read_worker` | `_stock_news_handler()` | 是 | 是 | 是 | 个股新闻事件 |
| `market.get_stock_rag` | `stock_rag` | read | `main_agent`,`read_worker` | `_stock_rag_handler()` | 是 | 是 | 是 | 个股 RAG 证据 |
| `system.scheduler_status` | `scheduler_status` | system | `main_agent` | `_scheduler_status_handler()` | 部分 | 是 | 是 | 单任务可 v2；多任务中因 `OP_SYSTEM` 会落到旧 fallback |
| `report.list_latest` | `report` | read | `main_agent`,`read_worker` | `_report_handler()` | 是 | 是 | 是 | 最新报告列表 |

执行器证据：

- `agent/tool_engine.py:262`：`class ToolExecutor`
- `agent/tool_engine.py:276`：`ToolExecutor.execute()`
- `agent/tool_engine.py:307`：通过 `execute_with_policy()` 执行 handler
- `agent/tool_engine.py:324`：调用 `save_tool_result_artifact()`

## 3. 旧版注册工具清单

来源：`agent/tools/tool_registry.py:get_tool_registry()`，共 26 个。

| tool name | permission | approval | current primary path | v2 migrated | migration status | risk |
| --- | --- | --- | --- | --- | --- | --- |
| `stock_lookup` | read | 否 | `agent/tools/stock_lookup_tool.py:lookup_stock()` | 否 | legacy only | P1 |
| `stock_analysis` | read | 否 | v2 + legacy fallback | 是 | partially migrated | P2 |
| `stock_news` | read | 否 | v2 + legacy fallback | 是 | partially migrated | P2 |
| `stock_rag` | read | 否 | v2 + legacy fallback | 是 | partially migrated | P2 |
| `ranking` | read | 否 | v2 + legacy fallback | 是 | partially migrated | P2 |
| `user_profile` | read | 否 | `agent/tools/user_profile_tool.py:query_user_profile()` | 否 | legacy only | P1 |
| `portfolio_state` | read | 否 | v2 + legacy fallback | 是 | partially migrated | P2 |
| `portfolio_risk` | read | 否 | v2 + legacy fallback | 是 | partially migrated | P2 |
| `position_recommendation` | read | 否 | `agent/executor.py:3042` direct branch | 否 | legacy direct | P1 |
| `replacement_recommendation` | read | 否 | `agent/executor.py:3057` direct branch | 否 | legacy direct | P1 |
| `manual_position_operation_tool` | preview | 是 | `agent/tools/manual_position_operation_tool.py:56` | 否 | legacy proposal | P1 |
| `strategy_builder_tool` | preview | 是 | `agent/tools/strategy_builder_tool.py:prepare_strategy_change()` | 否 | legacy proposal | P1 |
| `strategy_management_tool` | preview | 是 | `agent/tools/strategy_management_tool.py:16` | 否 | legacy proposal/write mix | P0 |
| `rebalance_plan` | preview | 是 | `agent/tools/rebalance_plan_tool.py` | 否 | legacy proposal | P1 |
| `adjust_position` | preview | 是 | `agent/executor.py:3150` direct branch | 否 | legacy proposal | P1 |
| `paper_trade_preview` | preview | 是 | `agent/tools/paper_trade_preview_tool.py` | 否 | legacy proposal | P2 |
| `paper_trade_execute` | write | 是 | `agent/tools/paper_trade_execute_tool.py:342` | 否 | legacy commit | P0/P1 |
| `paper_trading_execution_tool` | write | 是 | legacy registry alias/path | 否 | legacy commit | P1 |
| `strategy_confirmation_execute` | write | 是 | `agent/tools/strategy_management_tool.py:155` | 否 | legacy commit | P1 |
| `capital_management_preview` | preview | 是 | `agent/tools/capital_management_tool.py:13` | 否 | legacy proposal | P1 |
| `capital_management_execute` | write | 是 | `agent/tools/capital_management_tool.py:74` | 否 | legacy commit | P0/P1 |
| `backfill_preview` | preview | 是 | `agent/tools/backfill_tool.py:11` | 否 | legacy proposal | P1 |
| `backfill_execute` | write | 是 | `agent/tools/backfill_tool.py:46` | 否 | legacy commit | P0/P1 |
| `scheduler_status` | read | 否 | v2 single path; legacy multi fallback | 是 | partially migrated | P1 |
| `report` | read | 否 | v2 + legacy fallback | 是 | partially migrated | P2 |
| `python_sandbox_analysis` | read | 否 | `agent/orchestration/multi_task_executor.py:404` | 否 | legacy direct | P1 |

## 4. 旧入口和绕过路径

| 入口 | 文件/行 | 调用方式 | 是否绕过 v2 | 风险 |
| --- | --- | --- | --- | --- |
| 旧 AgentCore dispatch | `agent/agent_core.py:219` | `_dispatch()` 直接返回 `tool_adapter.*` 或 `generate_daily_agent_report` | 是 | P1，保留了一套旧问答 Agent 工具路径 |
| 旧 AgentCore 执行 | `agent/agent_core.py:313` | `tool_func(**tool_args)` | 是 | P1，无统一 ToolExecutor/Artifact |
| 主 executor 读工具 | `agent/executor.py:2998-3035` | v2 `_registered_tool()` 优先 | 否/部分 | P2，可保留但需收敛 fallback |
| 主 executor 写/建议工具 | `agent/executor.py:3042-3217` | 大量 direct branch | 是 | P1/P0，写工具未统一 |
| 多任务执行器 v2 优先 | `agent/orchestration/multi_task_executor.py:298-313` | 只对 v2 read tool 走 `ToolExecutor` | 部分 | P1，非 read/system 落旧路径 |
| 多任务旧 fallback | `agent/orchestration/multi_task_executor.py:326-413` | 直接调用 legacy tools | 是 | P1 |
| RiskOperation 专业 Agent | `agent/specialists/risk_operation.py:run()` | 直接调用 `preview_manual_position_operation()` | 是 | P1，未统一工具权限/Artifact |
| Agent 页面确认按钮 | `app/pages/ai_agent.py:1148-1166` | 直接调用确认执行函数 | 是 | P0，虽然有确认 token，但绕过 ToolExecutor |
| Agent 页面状态快捷查询 | `app/pages/ai_agent.py:1195-1210` | 直接调用 `query_portfolio_state()`、`query_scheduler_status()` | 是 | P2，读路径不统一 |
| AI 模拟盘页面回填 | `app/pages/ai_paper_trading.py:1289` | 直接调用 `run_ai_paper_backfill()` | 是 | P0，业务写/重放绕过 Agent 审批链 |
| AI 模拟盘页面资金流 | `app/pages/ai_paper_trading.py:1325` | 直接调用 `add_paper_cash_flow()` | 是 | P0，资金写绕过 Agent 审批链 |
| MCP registry bridge | `agent/mcp/registry_bridge.py:102` | `call_mcp_tool()` 返回旧 `ToolResult` | 是 | P1，MCP 未进入 v2 `ToolDefinition` |

## 5. MCP 当前状态

真实代码：

- `agent/mcp/schema_adapter.py:41`：`mcp_tool_to_tool_spec()` 将 MCP tool 映射成旧 `ToolSpec`。
- `agent/mcp/client_manager.py:35`：`call_mcp_tool()` 返回旧 `ToolResult`。
- `agent/mcp/registry_bridge.py:102`：bridge 调用 MCP。
- `agent/mcp/example_server.py:170`：示例只读工具 `market_risk_summary()`。
- `agent/mcp/example_server.py:35`：示例危险写工具 `unsafe_write_trade`。

审计判断：

- 默认本地配置下 MCP 未成为 Phase 11 工具引擎的 v2 `ToolDefinition`。
- 开启本地示例时，`market_risk_summary` 可以作为只读 MCP 证据工具被发现；`unsafe_write_trade` 被安全策略拦截/不映射。
- MCP 结果尚未统一为 `UnifiedToolResult`，也没有自动走 `ToolExecutor` artifact 保存。

迁移风险：P1。建议先只把允许的只读 MCP 工具映射为 v2 read `ToolDefinition`，继续禁止任何 MCP 写工具。

## 6. Artifact 与缓存

真实代码：

- `agent/artifacts.py:103`：`artifact_cache_key()`
- `agent/artifacts.py:183`：`ArtifactStore`
- `agent/artifacts.py:313`：`ArtifactStore.find_reusable()`
- `agent/artifacts.py:340`：`save_tool_result_artifact()`
- `agent/tool_engine.py:324`：v2 执行后保存 tool result artifact
- `agent/orchestration/multi_task_executor.py:1079`：`artifact_result_cache` 同轮内存缓存
- `agent/orchestration/multi_task_executor.py:1364`：初始化同轮 cache

审计判断：

- v2 工具执行时，只要 context 带 `db_path` 或 `output_dir`，会保存 artifact。
- artifact 保存会做敏感字段清理，覆盖 `token`、`confirmation_token`、`tushare_token`、`llm_api_key` 等字段。
- 多任务执行器只使用同轮 in-memory cache，未调用 `ArtifactStore.find_reusable()` 做跨轮复用。
- UI 展示当前主要依赖 runtime/result 字段，不是统一从 artifact store 读取。

风险：P2。Artifact 架构可用，但尚未成为所有工具输出的统一交换协议。

## 7. 能力索引审计

来源：`agent/capability_index.py:391`，`build_trusted_capability_index()`。

当前能力索引生成 23 条记录：

- 8 条来自 v2 核心工具。
- 14 条来自旧工具注册表中的可迁移工具。
- 1 条 workflow：`workflow:readonly_target_portfolio_allocation`。

能力记录包括：

| capability | read/write | tools | approval | agents |
| --- | --- | --- | --- | --- |
| `tool:portfolio_state` | read | `portfolio_state`,`portfolio.get_state` | 否 | supervisor, portfolio_analysis, reporting |
| `tool:portfolio_risk` | read | `portfolio_risk`,`portfolio.analyze_risk` | 否 | supervisor, portfolio_analysis, reporting |
| `tool:ranking` | read | `ranking`,`market.get_ranking` | 否 | supervisor, market_intelligence, portfolio_analysis, reporting |
| `tool:stock_analysis` | read | `stock_analysis`,`market.analyze_stock` | 否 | supervisor, market_intelligence, portfolio_analysis, reporting |
| `tool:stock_news` | read | `stock_news`,`market.get_stock_news` | 否 | supervisor, market_intelligence, portfolio_analysis, reporting |
| `tool:stock_rag` | read | `stock_rag`,`market.get_stock_rag` | 否 | supervisor, market_intelligence, portfolio_analysis, reporting |
| `tool:scheduler_status` | read | `scheduler_status`,`system.scheduler_status` | 否 | supervisor |
| `tool:report` | read | `report`,`report.list_latest` | 否 | supervisor, reporting |
| `tool:position_recommendation` | read | `position_recommendation` | 否 | portfolio_analysis |
| `tool:manual_position_operation_tool` | write | `manual_position_operation_tool` | 是 | risk_operation |
| `tool:rebalance_plan` | write | `rebalance_plan` | 是 | risk_operation |
| `tool:adjust_position` | write | `adjust_position` | 是 | risk_operation |
| `tool:paper_trade_execute` | write | `paper_trade_execute` | 是 | risk_operation |
| `tool:capital_management_preview` | write | `capital_management_preview` | 是 | risk_operation |
| `tool:capital_management_execute` | write | `capital_management_execute` | 是 | risk_operation |
| `tool:backfill_preview` | write | `backfill_preview` | 是 | risk_operation |
| `tool:backfill_execute` | write | `backfill_execute` | 是 | risk_operation |
| `tool:strategy_builder_tool` | write | `strategy_builder_tool` | 是 | risk_operation |
| `tool:strategy_management_tool` | write | `strategy_management_tool` | 是 | risk_operation |
| `tool:strategy_confirmation_execute` | write | `strategy_confirmation_execute` | 是 | risk_operation |
| `tool:paper_trade_preview` | write | `paper_trade_preview` | 是 | risk_operation |
| `tool:paper_trading_execution_tool` | write | `paper_trading_execution_tool` | 是 | risk_operation |
| `workflow:readonly_target_portfolio_allocation` | read | `portfolio_state`,`portfolio_risk`,`ranking` | 否 | supervisor, portfolio_analysis, reporting |

未进入能力索引但仍存在的旧注册工具：

- `stock_lookup`
- `user_profile`
- `replacement_recommendation`
- `python_sandbox_analysis`

审计判断：

- 能力索引没有暴露 handler 文件路径，符合避免前端泄露实现细节的目标。
- `registered_tool_names` 会出现 workflow 复用 `portfolio_state`、`portfolio_risk`、`ranking`，但没有重复 `capability_id`。
- 能力索引不是执行器，不能替代统一工具调用迁移。

## 8. 写操作安全链路

| 操作 | 预览/确认代码 | Revalidate/Commit | 当前问题 |
| --- | --- | --- | --- |
| 手动调仓预览 | `agent/tools/manual_position_operation_tool.py:56` | 委托 `rebalance_plan_tool` 生成确认计划 | 未经 v2；RiskOperation 直调 |
| 加仓/调仓预览 | `agent/tools/rebalance_plan_tool.py:144`、`:425` | 生成 `execute_add_stock` / `execute_adjust_position` plan | 未经 v2 |
| 确认执行模拟交易 | `agent/tools/paper_trade_execute_tool.py:342` | 校验 token、plan hash、业务状态、幂等 commit | 未经 v2；UI 直接调用 |
| 策略变更预览 | `agent/tools/strategy_builder_tool.py:192` | 生成 `register_strategy` plan | 未经 v2 |
| 策略启用确认 | `agent/tools/strategy_management_tool.py:155` | `execute_confirmed_strategy_plan()` | 未经 v2 |
| 策略禁用 | `agent/tools/strategy_management_tool.py:116` | 直接 `registry.disable()` | P0：实际写操作缺少确认闭环 |
| 资金变更预览 | `agent/tools/capital_management_tool.py:13` | 生成 `capital_change` plan | 未经 v2 |
| 资金变更确认 | `agent/tools/capital_management_tool.py:74` | 校验确认后 `add_cash_flow()` | 未经 v2；AI 模拟盘页面存在直调 |
| 历史回填预览 | `agent/tools/backfill_tool.py:11` | 生成 `paper_backfill` plan | 未经 v2 |
| 历史回填确认 | `agent/tools/backfill_tool.py:46` | 校验确认后 `run_paper_trading_backfill()` | 未经 v2；AI 模拟盘页面存在直调 |

P0 结论：

1. `agent/tools/strategy_management_tool.py:116` 的 `disable` 分支是确认声明下的真实写绕过。
2. `app/pages/ai_paper_trading.py:1289` 直接回填可能重放/改写模拟盘状态，绕过 Agent 审批。
3. `app/pages/ai_paper_trading.py:1325` 直接新增资金流水，绕过 Agent 审批。
4. `app/pages/ai_agent.py:1148-1166` 的确认按钮虽然有 token/plan，但绕过 `ToolExecutor`、统一 runtime policy 和 artifact。

## 9. 意图和场景追踪

以下结果来自本轮只读调用链追踪，没有改代码。

| 场景 | 识别结果 | route | 任务计划 | 判断 |
| --- | --- | --- | --- | --- |
| 查看当前持仓 | `portfolio_state` | `single_read_task` | `portfolio_state` | 可用；偶发显式参数污染需要后续处理 |
| 分析当前持仓风险 | `multi_intent` | `read_only_dag` | `portfolio_state -> portfolio_risk` | 可用；符合读 DAG |
| show top 10 ranking and analyze each stock | `multi_intent` | `read_only_dag` | `ranking -> stock_analysis` | 任务计划可用；semantic goal 偏 fallback |
| 推荐一个减仓后更稳健的组合 | `multi_intent` | `read_only_dag` | `portfolio_state -> portfolio_risk -> ranking` | 可用；只读建议，不提交 |
| 直接说今天应该持有哪些股票，每只多少仓位 | `one_time_position_operation` | `proposal_flow` | `one_time_position_operation` | 语义偏写预览，建议后续区分“建议”和“执行计划” |
| 把 600176 调整到 5% | `one_time_position_operation` | `proposal_flow` | `one_time_position_operation` | 正确进入审批预览 |
| 按刚才方案执行 | `general_help`/blocked validation | `single_read_task` | blocked | 无 pending plan 时被校验阻断，但 UX 会落 general_help |
| 新闻和 RAG 分析 600176 | `stock_news` | `single_read_task` | `stock_news` | 漏掉 `stock_rag`，复合意图仍需增强 |
| show current portfolio risk and recommend stable allocation with market evidence | `multi_intent` | `read_only_dag` | `portfolio_state -> portfolio_risk -> ranking` | 默认未选择 MCP；MCP 配置未启用时正常 |

重要文件：

- `agent/router.py`：路由入口。
- `agent/goal_planning.py`：UserGoal/TaskPlan。
- `agent/intent_decomposition/layered_decomposer.py`：规则/LLM 分层拆解。
- `agent/executor.py:2558`：`run_agent_request()` 主入口。
- `agent/orchestration/multi_task_executor.py:1758`：同步多任务执行入口。
- `agent/orchestration/multi_task_executor.py:1292`：异步多任务执行入口。

## 10. 重复业务逻辑区域

| 领域 | 重复位置 | 风险 |
| --- | --- | --- |
| 账户/持仓读取与摘要 | `portfolio/storage.py`、`portfolio/paper_account.py`、`agent/tools/portfolio_state_tool.py`、`pipelines/paper_trading_pipeline.py`、`pipelines/historical_account_replayer.py` | 口径漂移，前端和 Agent 结果不一致 |
| 风险分析 | `portfolio/portfolio_risk.py`、`agent/tools/portfolio_risk_tool.py`、`pipelines/paper_trading_pipeline.py`、`agent/tools/paper_trade_execute_tool.py` | 风险等级/指标重复计算 |
| ranking/个股分析 | `agent/tools/ranking_tool.py`、`agent/tools/stock_lookup_tool.py`、`agent/tools/stock_analysis_tool.py`、`agent/tool_adapter.py`、`app/classic_services.py` | 新旧页面/Agent 结果不一致 |
| 新闻/RAG | `agent/tools/stock_news_tool.py`、`agent/tools/stock_rag_tool.py`、`rag/`、`pipelines/rag_pipeline.py`、`agent/tool_adapter.py`、`news_db_sync.py`、`scripts/resync_news_rag.py` | 证据召回口径分裂 |
| 组合建议/一手约束 | `agent/tools/position_recommendation_tool.py`、`agent/tools/rebalance_plan_tool.py`、`portfolio/target_weight_allocator.py`、`portfolio/rebalance_rules.py`、`pipelines/paper_trading_pipeline.py`、`scoring/final_score.py` | 建议、预览、回放可能不一致 |
| 写操作确认 | `agent/session/confirmation_manager.py`、`agent/tools/paper_trade_execute_tool.py`、`agent/tools/capital_management_tool.py`、`agent/tools/backfill_tool.py`、`agent/tools/strategy_management_tool.py`、`app/pages/*.py` | 审批链闭环不统一 |

## 11. 测试结果

本轮执行的只读/临时数据测试：

| 命令 | 结果 |
| --- | --- |
| `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts` | 通过 |
| `py -3 -m pytest tests\unit\test_phase11* -q` | 未运行；pytest 未展开该路径通配，报告为 file not found |
| `py -3 -m pytest tests\unit\test_phase10* -q` | 未运行；pytest 未展开该路径通配，报告为 file not found |
| `py -3 -m pytest tests\unit\test_phase11_intent_tool_engine.py tests\unit\test_phase10_goal_planning.py tests\unit\test_phase10_3_capability_artifacts.py tests\unit\test_agent_write_requires_confirmation.py tests\unit\test_agent_action_proposal_gateway.py tests\unit\test_multi_agent_phase3_human_approval.py tests\unit\test_mcp_phase9_financial_evidence.py -q` | 53 passed, 2 failed |

失败用例：

1. `tests/unit/test_multi_agent_phase3_human_approval.py::test_phase3_correct_confirmation_revalidates_commits_same_run`
2. `tests/unit/test_multi_agent_phase3_human_approval.py::test_phase3_duplicate_confirmation_is_idempotent`

复现确认结果：

- 预览阶段成功，进入 `waiting_for_approval` 并生成 plan。
- 确认阶段返回 `success=False`。
- 错误为 `non_trading_day`。
- 消息：`2026-07-04 is not an A-share trading day; no paper order was generated.`
- 当前日期 2026-07-04 是周六，说明该测试依赖真实系统日期，测试本身缺少交易日注入/冻结。
- 失败发生在临时测试数据库，不涉及真实业务数据。

审计判断：这是确认提交链路的测试稳定性问题，也是审批闭环验收的风险。后续修复应优先让测试固定交易日或注入 trading calendar，而不是放松交易日校验。

## 12. 迁移优先级

### P0：必须先处理的安全和审批绕过

1. `agent/tools/strategy_management_tool.py:116`：`disable` 分支直接写策略 registry，缺少确认计划。
2. `app/pages/ai_paper_trading.py:1289`：页面直接执行 `run_ai_paper_backfill()`。
3. `app/pages/ai_paper_trading.py:1325`：页面直接执行 `add_paper_cash_flow()`。
4. `app/pages/ai_agent.py:1148-1166`：确认按钮直调 commit 函数，缺少统一 `ToolExecutor`/artifact/runtime policy。

### P1：下一阶段迁移到 v2 工具引擎

1. `position_recommendation`
2. `replacement_recommendation`
3. `manual_position_operation_tool`
4. `rebalance_plan` / `adjust_position`
5. `paper_trade_execute`
6. `capital_management_preview` / `capital_management_execute`
7. `backfill_preview` / `backfill_execute`
8. MCP read-only tools
9. `python_sandbox_analysis`
10. `scheduler_status` 多任务 system fallback

### P2：收敛重复读逻辑和前端展示口径

1. `agent/tool_adapter.py` 旧问答工具逐步挂到 v2 或下线。
2. `stock_lookup`、`user_profile`、`replacement_recommendation` 纳入能力索引或明确废弃。
3. 新闻 + RAG 的复合意图补齐。
4. ArtifactStore 跨轮复用接入多任务执行器。
5. 前端 Agent 执行信息统一读取 runtime/artifact，而不是混用 result dict。

### P3：工程清理

1. 清理旧 `agent/tool_adapter.py` 中乱码文案。
2. 给所有 v2 工具补充更明确的 test status 来源。
3. 统一 `ToolResult`、dict、`UnifiedToolResult` 的兼容边界。
4. 为迁移后的工具补充 contract/smoke 测试。

## 13. 最小侵入式迁移建议

第一阶段只做一个闭环：修复 P0 写绕过，并为写工具建立 v2 壳，不改业务实现。

建议文件清单：

| 文件 | 新增/修改 | 目的 | 与现有代码关系 |
| --- | --- | --- | --- |
| `agent/tool_engine.py` | 修改 | 增加 proposal/write `ToolDefinition`，handler 仍委托现有工具函数 | 不重写业务逻辑，只统一入口 |
| `agent/tools/strategy_management_tool.py` | 修改 | 将 `disable` 改为确认预览，不直接写 | 修复 P0 安全边界 |
| `app/pages/ai_agent.py` | 修改 | 确认按钮走统一 write executor 或专门 approval gateway | 保留 UI，统一 runtime/artifact |
| `app/pages/ai_paper_trading.py` | 修改 | 资金/回填写操作改成生成确认计划或调用统一 gateway | 避免页面直接写业务数据 |
| `tests/unit/test_phase11_intent_tool_engine.py` | 修改 | 增加 write/proposal 工具 v2 contract 测试 | 验收统一执行入口 |
| `tests/unit/test_multi_agent_phase3_human_approval.py` | 修改 | 固定交易日或注入 calendar | 修复日期敏感失败 |

第一阶段暂不做：

- 不迁移 LangChain/LangGraph/AutoGen/CrewAI。
- 不重写 RAG、模拟盘、Runtime、审批数据库。
- 不改变业务规则和一手约束。
- 不允许 MCP 写工具。

验收：

1. 所有 P0 入口不再直接写业务状态。
2. 写操作必须产生 confirmation plan。
3. 确认后必须 revalidate，再 commit。
4. write/proposal 工具能返回统一结果或兼容 legacy result。
5. 相关测试在固定交易日下稳定通过。

回滚：

- 保留现有业务函数不动；v2 handler 只是委托。
- UI 改动通过一个 gateway 函数切换，必要时可回到旧按钮但不建议。
- 数据库 schema 不变，无需迁移回滚。

## 14. 禁止事项

1. 不要为了迁移工具重写模拟盘引擎。
2. 不要放松确认、重新校验、幂等和交易日规则。
3. 不要让 LLM 或 MCP 直接提交写操作。
4. 不要把能力索引当成执行器。
5. 不要把 UI 页面直调视为安全的 Agent 执行链。
6. 不要在迁移中复制账户、风险、ranking、RAG 业务逻辑；应委托现有函数。

