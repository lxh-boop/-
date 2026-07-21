# 项目文件目录与作用说明

更新时间：2026-07-17

本文面向 AI、Codex 和新接手开发者，用于快速判断“文件在哪里、负责什么、改某个功能先看哪里”。高层架构和运行链路见 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)。

免责声明必须保留：

```text
本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
```

注意：

- `data/`、`models/`、`outputs/`、`runtime/`、`logs/`、`dist/`、`build/`、`installer_output/` 通常是本地数据、模型、构建或运行产物，默认不要提交。
- `local_app_config.json` 可能包含 Tushare Token、AI API Key 或本机配置，不要提交，不要在回复或日志中打印具体内容。
- 旧本地 MLP / `torch_mlp` 链路已经移除，不要恢复旧训练、旧模型保存或旧预测入口。
- 当前默认模型路线是外部模型：`Model Zoo: zoo:chronos_bolt_small` 和 `DFT_UNET: dft_unet_external`。

## 当前开发运行环境

```text
项目根目录：D:\stock_daily_app
项目虚拟环境：D:\stock_daily_app\.venv
虚拟环境基础解释器：D:\python_runtime\cpython-3.12.0-windows-x86_64-none\python.exe
Streamlit 地址：http://127.0.0.1:8501
健康检查：http://127.0.0.1:8501/_stcore/health
```

所有源码开发、测试、每日更新和本地 Web 启动命令均应显式调用 `.\.venv\Scripts\python.exe`。不要使用 `py -3`、裸 `python` 或 C 盘 Python。当前 8501 部署仅监听本机 `127.0.0.1`。

## 根目录核心文件

| 文件 / 目录 | 作用 |
|---|---|
| `AGENTS.md` | Codex 接手说明、业务边界、运行方式和禁止事项。 |
| `README.md` | 项目概览和常用启动说明。 |
| `PROJECT_STRUCTURE.md` | 高层架构、主运行链路、当前阶段能力和接手优先级。 |
| `PROJECT_FILE_DIRECTORY.md` | 当前文件级目录说明。 |
| `requirements.txt` | 主应用依赖。 |
| `requirements-desktop.txt` | Windows 桌面启动和打包依赖，例如 `pywebview`、`pyinstaller`。 |
| `requirements-ragas.txt` | Ragas 离线评测相关依赖。 |
| `.venv/` | 项目虚拟环境；当前绑定 D 盘 CPython 3.12.0，开发和本地部署必须通过 `.\.venv\Scripts\python.exe` 运行，默认不提交。 |
| `.streamlit/config.toml` | Streamlit 本地/发布配置，只监听本机地址并关闭不必要统计。 |
| `config.py` | 全局配置：Universe、Qlib 路径、输出目录、默认回放日期、模型参数等。 |
| `core/config/paths.py` | 开发模式和冻结发布模式的统一路径策略。 |
| `runtime_paths.py` | `core/config/paths.py` 的兼容包装，供桌面发布入口使用。 |
| `app_version.py` | 桌面 EXE 和安装包共用版本号。 |
| `local_config.py` | 本地 APP 配置读写：Token、AI API 配置、默认用户等。 |
| `local_app_config.json` | 本机配置缓存，可能含密钥，不要提交或打印。 |
| `app.py` | Streamlit 主入口，负责侧边栏、页面路由、首页、每日更新触发和免责声明。 |
| `desktop_launcher.py` | Windows 桌面启动器，发布后生成 `StockDailyApp.exe`。 |
| `stock_daily_app.spec` | PyInstaller `onedir` 构建配置。 |
| `build_windows.ps1` | Windows 构建脚本，准备资源、运行 PyInstaller，并在可用时生成 Inno 安装包；当前仍会自行检测 `py`/`python`，不属于已验证的 D 盘 8501 启动链路。 |
| `daily_incremental_update.py` | 每日增量更新入口，只使用外部模型后端，生成最新排名。 |
| `auto_model_search.py` | 模型搜索兼容入口，转向内部搜索实现。 |
| `scheduler_manager.py` | APP 侧每日自动任务配置和状态管理。 |
| `backtest.py`、`backtest_engine.py`、`backtest_metrics.py`、`backtest_external_models.py`、`backtest_rebalance.py` | 回测入口、引擎、指标和外部模型回测辅助。 |
| `ranking_schema.py` | 排名结果字段规范。 |
| `risk_scoring.py`、`confidence_scoring.py`、`calibration.py` | 旧式评分、置信度和校准辅助，仍可能被兼容流程或测试引用。 |
| `market_context.py` | 市场上下文构造辅助。 |
| `llm_client.py`、`llm_prompts.py`、`llm_explainer.py` | OpenAI-compatible LLM 客户端、提示词和解释生成；`LLMClient` 通过不可变运行快照区分远程 API 与本机 Ollama，不自动回退。 |
| `core/llm/runtime_settings.py` | API / Ollama 双 profile 的迁移、解析与不可变运行快照；公开字典与哈希不包含 API Key。 |
| `core/llm/ollama_manager.py` | 固定 loopback Ollama 的版本、模型列表、推荐模型拉取、项目模型创建与 chat 验证；不执行任意用户命令。 |
| `news_data.py`、`news_features.py`、`event_rules.py`、`news_db_sync.py` | 新闻/公告读取、事件特征、规则和数据库同步。 |
| `rag_store.py`、`rag_indexer.py`、`rag_retriever.py`、`rag_utils.py` | 旧 RAG 兼容模块；新实现主要在 `rag/`。 |
| `github_auth_*.ps1/log`、`streamlit_*.log` | 本机辅助脚本或日志，通常不属于业务核心。 |

## 数据、特征和模型

| 文件 / 目录 | 作用 |
|---|---|
| `universe.py` | 股票池统一入口。默认 Universe 为 CSI300，优先读 `data/csi300_stock_pool.csv`，不要在业务代码手写 300 只股票。 |
| `data_local.py` | 本地 Qlib / CSV 历史行情读取。 |
| `data_tushare.py` | Tushare 行情接口，包含并发/批量拉取最近交易日日线的能力。 |
| `alpha158.py` | Alpha158 风格因子、未来收益标签和展示字段。 |
| `model_factory.py` | 根据后端名创建模型或预测器。 |
| `model_backends/` | 传统本地模型后端封装，目前保留 LightGBM 等兼容后端，不要恢复旧 MLP。 |
| `external_models/` | 外部模型适配，例如 DFT_UNET。 |
| `model_zoo/` | Model Zoo 时间序列模型库：下载器、注册表、元数据、OHLCV 窗口构造和适配器。 |
| `model_zoo_backend.py` | Streamlit 和每日更新使用的 Model Zoo 后端封装。 |
| `model_discovery/` | 模型候选发现、GitHub/HuggingFace/Paper/Web 搜索、候选存储和适配计划。 |
| `inspect_external_model.py`、`evaluate_external_models.py`、`diagnose_model_performance.py` | 外部模型检查、评估和诊断工具。 |

## APP 层

| 文件 / 目录 | 作用 |
|---|---|
| `app/__init__.py` | APP 包初始化。 |
| `app/classic_services.py` | Streamlit 页面使用的兼容服务层，转发用户画像、模拟盘、回放、资金流水等。 |
| `app/display_labels.py` | 页面中文标签、风险等级、动作标签映射。 |
| `app/components/compact_metric.py` | 紧凑指标卡组件，AI 模拟盘账户摘要使用。 |
| `app/reflection_ui.py` | Reflection Critic 安全摘要展示组件。 |
| `app/handoff_ui.py` | Handoff 安全摘要展示组件。 |
| `app/pages/ai_agent.py` | AI Agent 页面：多会话、对话、Proposal 草稿、Implementation/Activation/Position 独立确认卡片、审批和运行轨迹；确认 token 不向用户展示。 |
| `app/pages/ai_paper_trading.py` | AI 模拟盘页面：账户、持仓、订单、资金、回放、策略说明和组合展示。 |
| `app/pages/system_monitor.py` | 系统监控页面：数据、模型、RAG、Agent、组合五层指标、告警和历史快照。 |
| `app/pages/model_search.py` | 模型搜索与回测页面。 |
| `app/services/file_loader.py` | 安全读取 CSV / JSON，避免空文件或缺字段导致页面崩溃。 |
| `app/services/backtest_display.py` | 回测结果展示辅助。 |
| `app/services/model_search_results.py` | 模型搜索结果读取、筛选和默认策略保存。 |

### 当前 APP 顶层页面

`app.py` 当前顶层页面：

```text
首页 / 预测排名
AI 模拟盘
AI Agent
系统监控
```

首页的 RAG 检索和 AI 解释前端入口已移除；后端 RAG 与解释能力仍保留给 Agent 和服务层使用。

## Pipeline 层

| 文件 / 目录 | 作用 |
|---|---|
| `pipelines/schemas.py` | Pipeline 上下文和结果 schema，默认策略为 `hierarchical_top10`。 |
| `pipelines/pipeline_runner.py` | 通用 pipeline runner。 |
| `pipelines/prediction_pipeline.py` | 预测流水线，读取模型/ranking 结果并输出统一预测记录。 |
| `pipelines/signal_fusion_pipeline.py` | 多信号融合流水线。 |
| `pipelines/rag_pipeline.py` | RAG 检索流水线。 |
| `pipelines/report_pipeline.py` | 报告生成流水线。 |
| `pipelines/daily_update_pipeline.py` | 每日更新组合流水线。 |
| `pipelines/paper_trading_pipeline.py` | AI 模拟盘每日执行流水线，读取最终推荐、生成调仓计划并执行纸面订单。 |
| `pipelines/paper_backfill_pipeline.py` | 历史回放流水线，按交易日加载历史 ranking / AI 调整并保存每日账户状态。 |
| `pipelines/backfill_state.py` | 历史回放状态文件读写和旧结果备份。 |
| `pipelines/historical_prediction_loader.py` | 读取历史 ranking，保存用户级历史 ranking 快照。 |
| `pipelines/historical_ai_adjustment_loader.py` | 读取历史 AI 调整结果并与原始 ranking 对齐。 |
| `pipelines/historical_news_loader.py` | 历史新闻读取；前端回放默认 `skip_news=True`。 |
| `pipelines/historical_signal_importer.py` | 历史信号导入和同步。 |
| `pipelines/historical_account_replayer.py` | 失败或缺失交易日的持仓延续和账户 mark-to-market。 |
| `pipelines/historical_account_audit.py` | 历史账户备份和审计辅助。 |
| `pipelines/daily_result_source_audit.py` | 回放数据源完整性审计。 |
| `pipelines/full_replay_audit.py` | 全量回放审计辅助。 |
| `pipelines/replay_audit_ledger.py` | 逐日回放审计 JSON / Markdown 写入。 |
| `pipelines/fixed_top10_inputs.py` | 固定 Top10 回放输入规范化。 |
| `pipelines/replay_normalization.py` | 回放记录字段规范化。 |

## Portfolio / 模拟盘层

| 文件 / 目录 | 作用 |
|---|---|
| `portfolio/schemas.py` | 账户、持仓、订单、调仓计划、资金流水和设置的数据结构。 |
| `portfolio/storage.py` | 模拟盘文件和数据库存储，核心输出在 `outputs/portfolio/<user_id>/`。 |
| `portfolio/portfolio_snapshot.py` | 只读归一化快照构建器：`cash` 固定为未投资现金，按“现金 + 有效持仓市值”重算总资产；输出逐项 `calculation_trace` 和稳定 `snapshot_id`，拒绝跨用户/账户/显式快照时间、负数和 NaN/Inf。 |
| `portfolio/paper_account.py` | 创建账户、资金流水、账户指标和快照读取。 |
| `portfolio/paper_position.py` | 持仓对象创建、更新和序列化。 |
| `portfolio/paper_order.py` | 纸面订单对象创建和字段规范。 |
| `portfolio/paper_trading_engine.py` | 执行调仓计划：先卖后买，按价格、现金、费用和一手约束生成订单并更新账户。 |
| `portfolio/rebalance_rules.py` | 使用 `ResolvedStrategyConfig` 构建调仓计划；无 Binding 时保持默认 `hierarchical_top10`。 |
| `portfolio/hierarchical_top10_allocator.py` | 默认策略核心分配器：Top1-5、Top6-10、Top15 缓冲、现金、单股上限和一手约束。 |
| `portfolio/target_weight_allocator.py` | 通用目标权重分配器，处理价格有效性、现金保留、一手和成本。 |
| `portfolio/trading_permissions.py` | A 股交易权限、代码可交易性和业务限制规则。 |
| `portfolio/trading_cost_config.py` | 交易成本、现金比例、调仓阈值和策略模式配置。 |
| `portfolio/paper_strategy_config.py` | 模拟盘策略配置辅助。 |
| `portfolio/cash_flow.py` | 入金、出金、待生效资金流水和历史回放衔接。 |
| `portfolio/cash_flow_cli.py` | 资金流水命令行工具。 |
| `portfolio/performance_metrics.py` | 净值、收益、回撤等绩效指标。 |
| `portfolio/portfolio_risk.py` | 组合风险计算。 |
| `portfolio/account_reconciliation.py` | 账户、持仓、订单一致性核对。 |
| `portfolio/user_profile.py` | 用户画像、风险约束和默认配置。 |
| `portfolio/behavior_profile.py` | 用户行为画像。 |
| `portfolio/decision_attribution.py` | 单股决策归因，只读解释正式推荐、纸面决策和执行诊断。 |

## Strategies / 长期策略调整

| 文件 / 目录 | 作用 |
|---|---|
| `strategies/registry.py` | 内置策略和用户版本注册表；应用成功后的用户版本保持 `registered_disabled`。 |
| `strategies/binding_repository.py` | 保存用户/账户/生效日隔离的 Strategy Binding 及历史版本。 |
| `strategies/runtime_resolver.py` | 按用户、账户和交易日解析默认或 Binding 策略，生成规范化 `ResolvedStrategyConfig`。 |
| `strategies/adapters/hierarchical_top10_strategy.py` | 默认策略 adapter，将 config 传给原组合分配和调仓链。 |
| `agent/services/strategy_proposal_service.py` | Proposal 草稿、修订、版本历史、用户/账户/会话隔离。 |
| `agent/services/strategy_implementation_service.py` | 锁定 Proposal 版本并在 `runtime/strategy_drafts/` 生成隔离实现。 |
| `agent/services/strategy_validation_service.py`、`strategy_review_service.py`、`strategy_backtest_service.py` | schema、安全、接口、测试、隔离回测、diff、tradeoff 和 rollback 预览。 |
| `agent/services/strategy_apply_service.py` | 应用计划、hash 重校验、原子文件/Registry 写入、幂等和失败回滚。 |
| `agent/services/strategy_binding_service.py` | 未来策略启用/回滚计划与独立确认；不会修改当前持仓。 |
| `agent/services/strategy_position_service.py` | 当前仓位预览与第三次确认；重校验账户和 Binding 后调用原模拟盘 pipeline。 |
| `agent/services/strategy_context_service.py` | 汇总对话、Proposal、Binding、运行时策略及模拟盘状态。 |
| `agent/services/strategy_audit_service.py` | 按 Proposal/Implementation/Plan/Commit/Binding/Run/Conversation ID 重建脱敏审计链。 |
| `agent/tools/strategy_workflow_tools.py` | 长期策略只读、提案、实现、应用、Binding、当前仓位和审计工具包装。 |

## Scoring / AI 调整层

| 文件 / 目录 | 作用 |
|---|---|
| `scoring/schemas.py` | 原始预测、新闻调整、用户调整、融合输出等 schema。 |
| `scoring/final_score.py` | 构建最终推荐结果，保存 `final_recommendations_*.csv`。 |
| `scoring/signal_fusion.py` | 多信号融合。 |
| `scoring/news_adjustment.py` | 新闻影响调整。 |
| `scoring/user_adjustment.py` | 用户画像适配调整。 |
| `scoring/risk_penalty.py` | 风险惩罚。 |
| `scoring/rule_engine.py` | 规则引擎。 |
| `scoring/normalizers.py` | 分数、权重和调整倍率规范化。 |
| `scoring/explain.py` | 推荐解释辅助。 |
| `scoring/decision_logger.py` | 决策日志记录。 |

## Agent 层

| 文件 / 目录 | 作用 |
|---|---|
| `agent/agent_core.py` | 早期 Agent 核心执行入口，部分兼容测试仍引用。 |
| `agent/executor.py` | 当前 Agent 主执行器，串联 Goal Planning、TaskPlan、ToolExecutor、Context、Message、Memory、Observe/Replan、Reflection、Handoff 和结果汇总。 |
| `agent/llm_audit.py` | 脱敏的 LLM 调用收据；记录部署模式、provider、model、配置哈希、耗时和 schema 结果，不记录密钥、完整提示词或完整回复。 |
| `agent/logic_integrity.py` | 不依赖 LLM 的流程完整性安全门；校验资产快照、任务/完成契约、Replan 审计与写入边界，并在逻辑错误时返回不可写、不可覆盖的 `feature_unavailable` 状态。 |
| `agent/replan_execution.py` | Completion 与 Critic 的 `REPLAN_READONLY` 统一消费器；仅生成并执行已注册的只读工具计划，以计划/结果签名、输出差异、缺失项变化和轮次上限审计进展，重复或无进展立即停止。 |
| `agent/top_k.py` | TopK 单一解析器，按“用户明确值 → 任务值 → 请求默认值 → 工具默认值 → 系统兜底”确定 1–100 的有效数量。 |
| `agent/router.py`、`agent/intent_router.py` | Agent 路由辅助和旧意图路由兼容层。 |
| `agent/intent_classifier.py` | 意图分类。 |
| `agent/parameter_extractor.py` | 从自然语言提取参数。 |
| `agent/goal_planning.py` | Phase 10 UserGoal / TaskPlan 规划、能力缺口判断和完成契约。 |
| `agent/intent_decomposition/` | 分层意图拆解、LLM 拆解、规则 fallback、提示词和 schema。 |
| `agent/orchestration/` | 参数解析、多任务执行、结果聚合；支持并发只读任务和依赖顺序。 |
| `agent/tool_engine.py` | Phase 11 后的 v2 ToolExecutor 主路径，统一权限、适配器和工具执行。 |
| `agent/tools/tool_registry.py` | 工具注册中心，声明权限、副作用、是否需要确认、并发、超时和保留策略。 |
| `agent/tools/*_adapters.py` | v2 服务收敛后的工具适配器，Agent 默认路径优先走这些适配器。 |
| `agent/tools/*_tool.py` | 兼容工具包装，旧页面、测试或 pipeline 仍可能引用。 |
| `agent/services/` | 工具服务层：市场分析、证据/RAG、组合、风险、版本化长期策略闭环、写操作、系统辅助、用户画像等。 |
| `agent/write_gateway.py` | P0 写操作网关，负责 approval / revalidate / idempotency / commit 边界。 |
| `agent/session/confirmation_manager.py` | 确认令牌、审批和确认状态管理。 |
| `agent/session/pending_action_store.py` | 待确认动作存储。 |
| `agent/session/conversation_state.py` | 会话状态辅助。 |
| `agent/runtime.py` | Agent 运行、步骤、工具调用、来源、审批、提交等持久化记录。 |
| `agent/runtime_reliability.py` | 超时、重试、熔断、预算、checkpoint 和大输出摘要。 |
| `agent/context/` | Phase 12 ContextManager：上下文模型、Policy、Sanitizer、Store、Resolver、Window、Gatherer。 |
| `agent/communication/` | Phase 13 AgentMessage / MessageBus：消息模型、策略、清洗、存储、路由、轨迹和窗口。 |
| `agent/memory/` | Phase 14 MemoryManager：WorkingMemory、SQLite store、检索、候选提取、合并、剪枝、清洗和工具。 |
| `agent/react/` | Phase 15 Observe / Replan：Observation、ObservePolicy、Store、Trace、Context bridge 和 ReplanPolicy。 |
| `agent/reflection/` | Phase 16 Reflection Critic：只读审查、策略、清洗、窗口和存储。 |
| `agent/handoff/` | Phase 17 Multi-Agent Handoff：角色协议、Router、Policy、Sanitizer、Coordinator、Specialist adapter。 |
| `agent/specialists/` | 专业 Agent：Market Intelligence、Portfolio Analysis、Risk Operation、Reporting。 |
| `agent/mcp/` | MCP 只读金融证据接入，MCP 写工具继续禁止。 |
| `agent/artifacts.py` | Agent 产物引用、存储和摘要。 |
| `agent/capability_index.py` | On-demand capability index 和能力检索。 |
| `agent/agent_protocol.py`、`agent/agent_specs.py`、`agent/agent_registry.py` | Agent 输出协议、角色规格和注册表。 |
| `agent/sandbox.py`、`agent/tools/python_sandbox_tool.py` | 受限只读 Python 分析运行器和工具包装。 |
| `agent/*_agent.py`、`agent/*_tool.py` | 报告、组合问答、组合复盘、事件影响、模型监控等早期专业 Agent/工具，部分作为兼容层保留。 |

### 当前核心 Agent 工具边界

- 只读问题可调用 ranking、stock analysis、news/RAG、portfolio state/risk、scheduler/report/system 等工具。
- 组合风险纯分析只能保持只读风险链路，不应自动扩展到候选、买卖或调仓方案。
- 写操作必须经过 `write_gateway.py`，不能让 LLM、MCP 或 Specialist 直接写模拟盘或策略状态。
- 确认后必须重新校验业务状态，Commit 需要可追溯、幂等，并尽可能支持回滚/审计。

## RAG / 新闻 / 证据

| 文件 / 目录 | 作用 |
|---|---|
| `rag/` | 新 RAG 包：schema、切分、BM25、Dense、Hybrid、Reranker、metadata filter、索引存储和检索日志。 |
| `rag/bm25_retriever.py` | BM25 检索。 |
| `rag/dense_retriever.py` | Dense 检索。 |
| `rag/hybrid_retriever.py` | RRF/混合检索。 |
| `rag/reranker.py` | Reranker 接口；当前按项目实现进行二次排序。 |
| `rag/chunkers.py` | 新闻/文本切块。 |
| `rag/metadata_filter.py` | 元数据过滤。 |
| `rag/retrieval_logger.py` | 检索日志。 |
| `rag/retention_policy.py` | 新闻/索引保留策略。 |
| `news_mapping/` | 新闻实体、股票别名、概念映射、LLM 映射、mapping store 和 ingestion。 |
| `news_db_sync.py` | 新闻数据库同步和内容级 chunk 处理。 |
| `evaluation/ragas_eval/` | 真 Ragas 离线评测：配置、数据集、Answer/Faithfulness 适配、retrieval 指标、financial metrics、runner 和导出。 |

## Evaluation / Reliability

| 文件 / 目录 | 作用 |
|---|---|
| `evaluation/adjustment_metrics.py` | AI 调整效果指标。 |
| `evaluation/ai_adjustment_evaluator.py` | AI 调整效果评估。 |
| `evaluation/evaluation_pipeline.py` | 评估流水线。 |
| `evaluation/evaluation_store.py` | 评估结果和可靠度状态存储。 |
| `evaluation/reliability_updater.py` | 根据历史表现更新 AI 可靠度权重。 |
| `evaluation/system_monitor.py` | 统一系统监控采集器，只读采集数据、模型、RAG、Agent、组合指标和告警。 |
| `evaluation/news_rag_diagnostics.py` | 新闻 RAG 诊断。 |
| `evaluation/runtime_fault_injection.py` | Runtime 故障注入模拟。 |
| `evaluation/agent_harness/` | Agent 端到端 harness：case loader、runner、assertions、metrics、exporter。 |
| `evaluation/multi_agent/` | 多 Agent 评估：场景、fixtures、runner、metrics、benchmark、exporter。 |
| `evaluation/ragas_eval/` | Ragas 离线评测体系。 |

## Database

| 文件 / 目录 | 作用 |
|---|---|
| `database/connection.py` | SQLite 连接。 |
| `database/sqlite_store.py` | SQLite 存储封装。 |
| `database/schemas.py` | 表结构定义。 |
| `database/table_registry.py` | 表注册和 migration 辅助。 |
| `database/repositories/user_repository.py` | 用户配置 repository。 |
| `database/repositories/stock_repository.py` | 股票基础信息 repository。 |
| `database/repositories/news_repository.py` | 新闻和 RAG repository。 |
| `database/repositories/prediction_repository.py` | 预测 repository。 |
| `database/repositories/portfolio_repository.py` | 组合/模拟盘 repository。 |
| `database/repositories/agent_repository.py` | Agent runs、steps、tool calls、messages、approvals、commits、memory、artifacts 等 repository。 |
| `database/repositories/evaluation_repository.py` | 评估 repository。 |
| `database/repositories/system_monitor_repository.py` | 系统监控快照和告警 repository。 |
| `database/migrations/001_initial_schema.sql` 到 `023_paper_decision_strategy_metadata.sql` | 当前 SQLite migration 序列。`019`—`023` 增加 Proposal/Implementation、Strategy Binding、运行审计和纸面决策策略元数据；安装版首次启动只用 migration 初始化。 |
| `database/seed/agent_rules.example.json` | Agent 规则示例。 |

## Scheduler / 自动任务

| 文件 / 目录 | 作用 |
|---|---|
| `scheduler/daily_worker.py` | 每日任务 worker。 |
| `scheduler/user_job_runner.py` | 用户级任务执行。 |
| `scheduler/trading_calendar.py` | 交易日历、最近交易日和下一交易日判断。 |
| `scheduler/job_state.py` | 任务状态记录。 |
| `scheduler/job_lock.py` | 任务锁，避免重复运行。 |
| `scheduler/retry_policy.py` | 重试策略。 |
| `scheduler/health_check.py` | 调度健康检查。 |
| `scheduler/scheduler_cli.py` | 调度命令行入口。 |
| `scheduler/windows_task_installer.py` | Windows 任务计划安装辅助。 |
| `scripts/install_windows_daily_task.ps1` | 安装 Windows 每日任务。 |
| `scripts/uninstall_windows_daily_task.ps1` | 卸载 Windows 每日任务。 |
| `scripts/run_scheduled_daily_update.ps1`、`scripts/run_scheduled_daily_update.bat` | Windows 调度执行脚本。 |

## Scripts / 构建、检查和维护

| 文件 / 目录 | 作用 |
|---|---|
| `scripts/start_local_web.ps1` | 本地启动 Streamlit Web 的辅助脚本；当前仍调用 `py`，D 盘 8501 部署不要使用该脚本，应显式调用 `.\.venv\Scripts\python.exe`。 |
| `scripts/setup_ollama_qwen3_4b.ps1` | 使用官方 Ollama CLI 拉取 `qwen3:4b`、创建 `stock-agent-qwen3-4b` 并验证本机 OpenAI-compatible 端点。 |
| `scripts/prepare_distribution_assets.py` | 构建前分发资源检查，不修改开发 live 数据库。 |
| `scripts/verify_distribution.py` | 构建后分发目录检查，确认 EXE、migration、resources 和敏感文件策略。 |
| `scripts/smoke_test_dist_exe.ps1` | Windows dist EXE 冒烟测试。 |
| `scripts/build_capability_index.py` | 构建 Agent capability index。 |
| `scripts/resync_news_rag.py` | 重新同步新闻 RAG。 |
| `scripts/run_runtime_fault_injection.py` | Runtime 故障注入运行入口。 |
| `scripts/run_system_monitor_snapshot.py` | 系统监控快照采集脚本。 |
| `scripts/check_phase12_context_web.py` | Phase 12 Context UI 网页检查。 |
| `scripts/check_phase13_communication_web.py` | Phase 13 Communication UI 网页检查。 |
| `scripts/check_phase15_react_loading_web.py` | Phase 15 ReAct/加载性能网页检查。 |
| `scripts/check_phase16_reflection_web.py` | Phase 16 Reflection 网页检查。 |
| `scripts/evaluate/`、`scripts/test/`、`scripts/model_search/` | 评估、测试和模型搜索辅助脚本。 |

## Windows 桌面发布

| 文件 / 目录 | 作用 |
|---|---|
| `docs/phase12_context_system_docs/WINDOWS_DISTRIBUTION.md` | Windows 桌面运行、PyInstaller、Inno Setup、用户数据目录和排错说明。 |
| `codex_tasks/37_PHASE_WINDOWS_DESKTOP_INSTALLER.md` | Windows 安装器阶段交接说明。 |
| `installer/StockDailyApp.iss` | Inno Setup 安装脚本。 |
| `resources/` | 发布版只读资源目录，包含默认配置、icons、database、agent_harness、ragas_eval 等资源子目录。 |
| `dist/StockDailyApp/` | PyInstaller onedir 输出目录，默认不提交。 |
| `installer_output/StockDailyApp_Setup_<version>.exe` | 安装包输出目录，默认不提交。 |

安装版用户数据目录：

```text
%LOCALAPPDATA%\StockDailyApp\
├── database/
├── outputs/
├── logs/
├── cache/
├── runtime/
├── config/
└── models/
```

开发模式仍使用项目根目录下的：

```text
data/
models/
outputs/
runtime/
logs/
local_app_config.json
```

## Docs / 阶段文档和交付报告

| 目录 / 文件 | 作用 |
|---|---|
| `docs/handoff/` | 项目接手文档、业务规则、数据字典、模型说明、纸面交易规则、数据源权威说明、开放决策等。 |
| `docs/phase12_context_system_docs/` | Phase 12 ContextManager 文档、阶段报告和最终报告。 |
| `docs/phase13_communication_system_docs/` | Phase 13 AgentMessage / CommunicationBus 文档、阶段报告和最终报告。 |
| `docs/phase14_memory_system_docs/` | Phase 14 MemoryManager 文档、阶段报告和最终报告。 |
| `docs/phase15_react_observe_replan_docs/` | Phase 15 ReAct Observe/Replan 文档、阶段报告和最终报告。 |
| `docs/phase16_17_reflection_handoff_docs/` | Phase 16 Reflection Critic 与 Phase 17 Handoff 文档、阶段报告和最终报告。 |
| `docs/strategy_adjustment_phases/` | 长期模拟盘策略调整 Phase 0—8 验收报告与最终报告。 |
| `docs/sample_data/` | 脱敏样例数据。 |
| `docs/screenshots/` | 页面检查截图。 |
| `docs/portfolio_risk_and_multi_conversation_audit_fix_report.md` | 组合风险意图边界和 AI Agent 多会话 UI 修复报告。 |
| `docs/diagnostics/AGENT_LOGIC_REPLAN_ASSET_RECHECK.md` | 112000/122000 资产夹具、现金语义和本次修复前基线复核记录。 |
| `docs/diagnostics/AGENT_LOGIC_REPLAN_ASSET_FIX_REPORT.md` | 资产口径、流程完整性、Replan 进展和故障提示的最终验收报告。 |
| `docs/diagnostics/AGENT_CAPABILITY_BENCHMARK_BASELINE.md` | L1 真实 LLM Agent 能力测评的模型入口、L0 对照、已知失败与严格隔离基线。 |
| `docs/diagnostics/AGENT_CAPABILITY_BENCHMARK_REPORT.md` | L1 隐藏集真实模型结果、门禁、延迟和可恢复续跑说明。 |
| `docs/diagnostics/AGENT_CAPABILITY_BENCHMARK_DIAGNOSTIC_REPORT.md` | 门禁不通过时由保留轨迹生成的低分自动诊断和最小复现。 |
| `docs/setup/LOCAL_LLM_SETUP.md` | 本地 Ollama 安装、模型创建、UI 手动切换和无自动回退说明。 |
| `docs/diagnostics/LOCAL_LLM_SWITCH_BASELINE.md`、`LOCAL_LLM_SWITCH_IMPLEMENTATION_REPORT.md` | 本地模型切换的排查基线、实现边界、测试结果和运行条件。 |

## 运行产物目录

| 目录 | 作用 |
|---|---|
| `data/` | 本地行情、特征、股票池、SQLite 开发数据库等。开发数据库为 `data/agent_quant.db`。 |
| `models/` | 外部模型文件、Model Zoo 下载、DFT_UNET 相关文件和缓存。 |
| `outputs/` | 最新排名、历史排名、报告、用户推荐、模拟盘账户/持仓/订单/净值等输出。 |
| `runtime/` | Streamlit 日志、job 状态、Agent artifacts、replay audit、`strategy_drafts` 隔离实现和临时运行文件。 |
| `logs/` | 训练、更新、APP、调度和诊断日志。 |
| `build/`、`dist/`、`installer_output/` | Windows 构建产物，默认不提交。 |
| `.venv/`、`.pytest_cache/`、`__pycache__/` | 本地虚拟环境和缓存，默认不提交；当前 `.venv/` 的基础解释器位于 `D:\python_runtime\cpython-3.12.0-windows-x86_64-none\python.exe`。 |

## L1 real-LLM benchmark audit and repair (2026-07-20)

| File / directory | Purpose |
|---|---|
| `agent/llm_audit.py` | Redacted durable `LLM_CALL` receipt store. It keeps transport timing/status/schema evidence only and never persists API keys, prompts, full responses or local paths. |
| `llm_client.py` | `LLMClient.chat_audited(...)` is the LLM-decomposition call path used when formal Agent audit context is active. |
| `agent/executor.py` | `run_agent_request` persists `formal_entry_used=true` and binds the executor-owned run/conversation/case context before Planner, Completion, Report or Critic calls. |
| `agent/intent_decomposition/llm_decomposer.py` | Maps actual calls to `planner`, `goal_reviewer`, `completion` and `critic`, with an explicit persisted schema-result record. |
| `benchmarks/agent_capability/scoring.py` | Validity partition, Agent-only aggregation, N/A-safe metric records and independent provider/infrastructure metrics. |
| `benchmarks/agent_capability/run_benchmark.py` | Isolated real-LLM runner; retries invalid infrastructure runs, preserves raw/failure evidence and refuses to publish an official hidden-set report with zero valid samples. |
| `tests/benchmark/test_agent_capability_pipeline_repair.py` | Regression tests for receipts, redaction, formal entry, conditional reviewer validity, provider/trace exclusion, zero-sample N/A and resume behavior. |
| `docs/diagnostics/AGENT_CAPABILITY_BENCHMARK_PIPELINE_REPAIR_BASELINE.md` | Pre-repair evidence baseline and failure taxonomy. |

## Tests

### Stable portfolio workflow diagnostics and benchmark

| File / directory | Purpose |
|---|---|
| `agent/runtime_reliability.py` | LLM token/call budget limits are disabled by default through `ENABLE_LLM_BUDGET_LIMITS`; independent tool, timeout, retry, step, Replan, approval and write safeguards remain active. |
| `agent/replan_execution.py` | Shared Replan state (`replan_count`, executed/attempted rounds, limit and audit) plus readonly task validation, signatures and progress records. |
| `agent/logic_integrity.py` | Terminal-priority guard. A logic error produces deterministic `feature_unavailable`, suppresses Completion/Critic Replan and blocks plan, approval and writes. |
| `agent/top_k.py` | Business TopK policy: explicit user value, task value, target holding count × 2 redundancy, request default, tool default, then system fallback. |
| `agent/tools/portfolio_comparison_tools.py` | Strict target-portfolio validation for total weight, cash, duplicate/unknown securities, single-position and industry limits, and explanation conflicts. |
| `benchmarks/agent/` | 84 stable-portfolio benchmark cases and resumable runner. |
| `tests/unit/test_stable_portfolio_workflow.py` | Regression tests for LLM budget policy, terminal suppression, Replan state, constraints, TopK and final-response message type. |
| `tests/benchmark/test_stable_portfolio_benchmark.py` | Release-gate test for benchmark volume and zero safety violations. |
| `outputs/benchmarks/agent/` | Generated raw JSONL, metrics JSON/CSV and Markdown benchmark report. |
| `docs/diagnostics/STABLE_PORTFOLIO_REPAIR_BASELINE.md` | Real-chain Phase 0 reproduction and baseline test results. |
| `docs/diagnostics/STABLE_PORTFOLIO_WORKFLOW_AND_BENCHMARK_REPORT.md` | Final stable-portfolio repair, verification and benchmark report. |
| `benchmarks/agent_capability/` | L1 真实 LLM Agent 能力测评：180 个 A–F 案例、隐藏 Gold、隔离 fixture、runner/resume、规范化轨迹和评分。 |
| `benchmarks/agent_capability/cases/` | 108 development、36 validation、36 hidden 案例；`hidden_gold.jsonl` 与隐藏输入分离，绝不注入模型 Prompt。 |
| `benchmarks/agent_capability/run_benchmark.py`、`resume.py` | 通过正式 Agent 入口执行真实 LLM，按 case + iteration + model-config hash checkpoint/续跑。 |
| `tests/benchmark/test_agent_capability_dataset.py` | L1 数据集数量、分层、隐藏 Gold 隔离与安全评分结构测试（不冒充真实 LLM 测试）。 |
| `outputs/benchmarks/agent_capability/` | L1 脱敏 raw/normalized traces、metrics、类别指标、失败轨迹、报告及隔离工作区。 |

| 目录 / 文件 | 作用 |
|---|---|
| `tests/unit/` | 大量单元和集成风格测试，覆盖模拟盘、Agent、RAG、Ragas、Context、Message、Memory、ReAct、Reflection、Handoff、Windows 构建等。 |
| `tests/fixtures/agent_questions.csv` | Agent harness 问题样例。 |
| `tests/unit/agent_control_center_utils.py`、`tests/unit/stage5q_helpers.py` | 测试辅助工具。 |

常用验证：

```powershell
.\.venv\Scripts\python.exe -m compileall -q agent app portfolio scoring rag pipelines database strategies scripts
.\.venv\Scripts\python.exe -m pytest tests\unit -q
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false
```

针对 Agent / UI 改动，至少补跑相关单测，并真实打开 8501 页面检查：首页、AI Agent、AI 模拟盘、系统监控。
