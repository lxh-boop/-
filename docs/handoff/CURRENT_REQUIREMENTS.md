# Current Requirements

本文档是当前需求的接手口径。若本文档与旧 prompt、旧页面文案或旧字段冲突，以本文档和标注的实现文件为准。

## 项目定位

本项目是 A 股每日股票评分、AI 调整、模拟盘和 Agent 展示系统。它用于机器学习、金融数据分析、量化因子建模和项目展示，不是荐股系统，不接券商接口，不构成投资建议，不用于实盘交易。

所有页面必须保留免责声明：

```text
本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
```

实现位置：

- `app.py`：Streamlit 主页面、每日预测排名、免责声明与页面入口。
- `app/pages/ai_paper_trading.py`：AI 模拟盘页面免责声明。
- `scoring/schemas.py`：`COMPLIANCE_DISCLAIMER`。
- `portfolio/schemas.py`：`PAPER_TRADING_DISCLAIMER`。
- `llm_prompts.py`：AI 解释相关合规边界。

## 当前有效功能

- 每日预测：从 `outputs/ranking_latest.csv` 展示当前排名，支持 TopK、图表、个股走势、模型指标。
- 模型：当前保留并实际可用的最佳外部模型是 `chronos_bolt_small`；旧本地 MLP 训练和兼容后端已经移除。
- AI 调整：根据模型预测、新闻证据、用户画像和 AI 可靠度生成仓位调整比例，不输出实盘交易建议。
- AI 模拟盘：仅 paper trading，策略固定为 `hierarchical_top10`，不允许前端任意改策略参数。
- 历史回放：默认从 `2026-04-01` 开始，可强制重建历史模拟盘交易。
- Agent：作为查询、解释、组合状态、调度和回放等项目操作入口；它不能绕过服务层直接写产物。

实现位置：

- `daily_incremental_update.py`：每日行情缓存、特征、排名生成。
- `model_zoo_backend.py`、`model_zoo/registry.py`、`models/external_zoo/metadata.json`：外部模型后端与当前下载模型。
- `scoring/final_score.py`、`scoring/signal_fusion.py`：AI 调整与最终推荐。
- `pipelines/paper_trading_pipeline.py`、`pipelines/paper_backfill_pipeline.py`：模拟盘和历史回放。
- `portfolio/rebalance_rules.py`、`portfolio/hierarchical_top10_allocator.py`、`portfolio/paper_trading_engine.py`：策略和纸面成交。
- `app/pages/ai_agent.py`、`agent/tools/`：Agent 页面和工具。

## 当前页面

- 首页 / 预测排名：`app.py`
- AI 模拟盘：`app/pages/ai_paper_trading.py`
- AI Agent：`app/pages/ai_agent.py`
- 模型搜索：`app/pages/model_search.py`
- 新闻、RAG、AI 解释、系统设置：在 `app.py` 的 tab 内实现。

## AI 权限边界

AI 只能做解释、证据检索、信号融合和 paper trading 计划生成。AI 不允许：

- 生成“买入/卖出/持有”的实盘指令。
- 连接真实券商或自动下单。
- 绕过 `portfolio/`、`pipelines/`、`database/repositories/` 直接改账户、订单或数据库。
- 把 RAG 相似度或新闻情绪直接当作收益预测。
- 硬编码或泄露 Tushare Token、LLM API Key。

实现位置：

- `scoring/schemas.py`：合规免责声明和输出字段过滤。
- `pipelines/daily_update_pipeline.py`：prediction -> rag -> scoring -> paper -> report 的受控流程。
- `agent/tools/tool_registry.py`、`agent/tools/tool_schemas.py`：Agent 工具边界。
- `portfolio/storage.py`：模拟盘落盘统一入口。

## 废弃字段和旧逻辑

以下字段不再是当前业务主链路的依据：

- `final_action`
- `watchlist`
- `exclude`
- `keep`
- `down_weight`
- 普通风险惩罚字段：`risk_penalty`、`risk_penalty_score`
- 规则惩罚字段：`rule_penalty`、`rule_penalty_score`

当前口径：

- AI 调整输出核心是 `news_adjustment`、`user_adjustment`、`effective_news_adjustment`、`combined_adjustment`、`position_adjustment_ratio`、`target_weight`。
- 模拟盘实际动作使用 `paper_action` 和真实订单字段，如 `paper_buy`、`paper_sell`、`paper_reduce`、`paper_hold`。
- 历史旧文件里可能仍有 `final_action` 或 `watchlist` 字段，只作为兼容读取，不作为新逻辑来源。

实现位置：

- `scoring/schemas.py`：`FusionOutput.to_dict()` 主动移除 `final_action`、`risk_penalty`、`rule_penalty` 等旧字段。
- `database/migrations/013_remove_action_and_penalty_fields.sql`：数据库迁移移除旧字段。
- `tests/unit/test_database_migration_removes_old_fields.py`：测试确认旧字段不在关键表中。
- `portfolio/storage.py`：写订单 CSV 时排除 `final_score`、`final_action`。
- `scoring/risk_penalty.py`、`scoring/rule_engine.py`：保留为兼容/旧实验模块，不是当前主链路。

## 当前默认参数

- Universe：`csi300`
- 模拟盘默认初始资产：`150000.0`
- 历史回放默认开始日：`2026-04-01`
- 模拟盘固定策略：`hierarchical_top10`
- 回放前端固定：`top_k=15`、`entry_top_k=10`、`hold_buffer_rank=15`、`max_positions=10`
- 目标现金：`5%`
- 单股上限：`30%`

实现位置：

- `config.py`
- `app/pages/ai_paper_trading.py`
- `portfolio/trading_cost_config.py`
- `pipelines/paper_trading_pipeline.py`
- `pipelines/paper_backfill_pipeline.py`

## 当前已知风险

- `daily_incremental_update.py` 的命令行入口当前主要支持 `zoo:*` 模型后端；旧本地 MLP 后端不再作为有效路径。
- 部分旧源码注释或页面文案存在编码历史问题；接手时优先看函数、字段和本文档，不要只按旧中文文案判断业务状态。
- `scoring/risk_penalty.py`、`scoring/rule_engine.py` 不应被重新接入主流程，除非先更新需求和测试。
