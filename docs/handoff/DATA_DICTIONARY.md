# Data Dictionary

本文档说明接手者最常遇到的输出文件、字段含义和样例位置。完整样例放在 `../sample_data/`，每个文件保留 5 到 10 行左右，已脱敏用户标识。

## 样例文件

| 样例 | 来源 | 用途 |
|---|---|---|
| `../sample_data/ranking_latest_sample.csv` | `outputs/ranking_latest.csv` | 首页当前每日预测排名 |
| `../sample_data/historical_ranking_sample.csv` | `outputs/rankings/history/ranking_YYYYMMDD.csv` | 历史回放使用的每日原始排名 |
| `../sample_data/final_recommendations_sample.csv` | `outputs/users/<user_id>/recommendations/final_recommendations_YYYYMMDD.csv` | AI 调整后推荐 |
| `../sample_data/paper_account_latest_sample.json` | `outputs/portfolio/<user_id>/paper_account_latest.json` | 模拟盘最新账户 |
| `../sample_data/paper_positions_latest_sample.csv` | `outputs/portfolio/<user_id>/paper_positions_latest.csv` | 模拟盘最新持仓 |
| `../sample_data/paper_orders_sample.csv` | `outputs/portfolio/<user_id>/history/orders/orders_YYYYMMDD.csv` 或累计订单 | 模拟盘订单 |
| `../sample_data/ai_paper_decisions_latest_sample.json` | `outputs/portfolio/<user_id>/ai_paper_decisions_latest.json` | 当日模拟盘决策 |
| `../sample_data/news_stock_mapping_sample.csv` | `outputs/news_stock_mapping_YYYYMMDD.csv` | 新闻与股票映射 |
| `../sample_data/news_event_sample.csv` | `outputs/news_api_test/*.csv` | 新闻事件样例 |

## ranking_latest.csv

核心路径：`outputs/ranking_latest.csv`

生成位置：

- `daily_incremental_update.py`：`make_latest_ranking(...)`
- `model_zoo_backend.py`：`make_zoo_latest_ranking(...)`
- `ranking_schema.py`：字段规范化和校验。

关键字段：

| 字段 | 含义 |
|---|---|
| `rank` | 当日排名，1 为最高 |
| `date` | 信号日期 |
| `code` | 6 位股票代码 |
| `name` | 股票名称 |
| `close` | 信号日收盘价 |
| `pct_chg` | 信号日涨跌幅 |
| `pred_5d_ret` | 预测收益或模型回归分数，当前外部模型可视为排序信号 |
| `raw_score` / `pred_score` | 原始模型分数 |
| `up_prob` | 上涨概率，可能经过校准或横截面 fallback |
| `up_prob_calibrated` | 校准后上涨概率 |
| `score` | 横截面排名分位数，越高排名越靠前 |
| `confidence_score` | 可信度数值 |
| `confidence` | 可信度等级 |
| `risk_score` | 风险分数 |
| `risk_level` | 风险等级 |
| `model_name` | 生成排名的模型名 |
| `ret_5` / `ret_20` | 过去 5/20 日收益 |
| `vol_20` | 过去 20 日波动 |
| `drawdown_20` | 过去 20 日回撤 |
| `prediction_date` | 预测面向的下一个交易日 |

## 历史 ranking

核心路径：

- `outputs/rankings/history/ranking_YYYYMMDD.csv`
- 用户回放快照：`outputs/portfolio/<user_id>/history/rankings/ranking_YYYYMMDD.csv`

读取位置：

- `pipelines/historical_prediction_loader.py`
- `pipelines/paper_backfill_pipeline.py`

关键字段：

| 字段 | 含义 |
|---|---|
| `stock_code` / `code` | 股票代码 |
| `stock_name` / `name` | 股票名称 |
| `trade_date` | 排名对应交易日 |
| `original_score` | 历史原始分数 |
| `original_rank` | 历史原始排名 |
| `current_price` / `close` | 当日价格 |
| `model_name` / `model_version` | 历史信号来源 |
| `pred_score` / `score` | 排序分数 |
| `pred_rank` / `rank` | 排名 |

## final_recommendations_*.csv

核心路径：

- `outputs/users/<user_id>/recommendations/final_recommendations_latest.csv`
- `outputs/users/<user_id>/recommendations/final_recommendations_YYYYMMDD.csv`

生成位置：

- `scoring/final_score.py`
- `pipelines/signal_fusion_pipeline.py`
- `pipelines/paper_backfill_pipeline.py`

关键字段：

| 字段 | 含义 |
|---|---|
| `trade_date` / `date` | 信号或推荐日期 |
| `stock_code` / `code` | 股票代码 |
| `stock_name` | 股票名称 |
| `original_pred_score` / `original_score` | 原始模型分数 |
| `original_pred_rank` / `original_rank` | 原始模型排名 |
| `news_adjustment` | 新闻调整 |
| `user_adjustment` | 用户画像调整 |
| `effective_news_adjustment` | 可靠度加权后的新闻调整 |
| `combined_adjustment` | 综合调整 |
| `original_target_weight` | 原始目标仓位 |
| `position_adjustment_ratio` | 仓位调整倍数 |
| `target_weight` | AI 调整后的目标仓位 |
| `ai_reliability_weight` | AI 可靠度 |
| `ai_adjustment_confidence` | 调整置信度 |
| `evidence_news_ids` / `evidence_chunk_ids` | 证据 ID |
| `reason` | 解释文本 |
| `compliance_disclaimer` | 合规声明 |

## paper_account_latest.json

核心路径：`outputs/portfolio/<user_id>/paper_account_latest.json`

生成位置：

- `portfolio/paper_account.py`
- `portfolio/storage.py`
- `portfolio/paper_trading_engine.py`

关键字段：

| 字段 | 含义 |
|---|---|
| `account_id` | 模拟账户 ID |
| `user_id` | 用户 ID |
| `initial_cash` | 初始资产 |
| `cash` | 当前现金 |
| `position_market_value` | 当前持仓市值 |
| `total_assets` | 总资产，现金加持仓市值 |
| `net_contribution` | 净投入资金 |
| `absolute_profit` | 绝对盈亏 |
| `daily_return` | 当日收益率 |
| `cumulative_return` | 累计收益率 |
| `time_weighted_return` | 时间加权收益率 |
| `composite_nav` / `nav` | 复合净值 |
| `max_drawdown` | 最大回撤 |
| `cumulative_fee` | 累计费用 |
| `is_paper_trading` | 恒为模拟盘标识 |

## paper_positions_latest.csv

核心路径：`outputs/portfolio/<user_id>/paper_positions_latest.csv`

生成位置：

- `portfolio/paper_position.py`
- `portfolio/storage.py`

关键字段：

| 字段 | 含义 |
|---|---|
| `position_id` | 持仓 ID |
| `user_id` | 用户 ID |
| `stock_code` / `stock_name` | 股票代码和名称 |
| `quantity` | 持仓数量 |
| `cost_price` | 成本价 |
| `current_price` | 当前价 |
| `market_value` | 市值 |
| `position_ratio` | 仓位占比 |
| `unrealized_pnl` | 浮动盈亏 |

## paper_orders*.csv

核心路径：

- 最新订单：`outputs/portfolio/<user_id>/paper_orders_latest.csv`
- 累计订单：`outputs/portfolio/<user_id>/paper_orders.csv`
- 历史订单：`outputs/portfolio/<user_id>/history/orders/orders_YYYYMMDD.csv`

生成位置：

- `portfolio/paper_order.py`
- `portfolio/paper_trading_engine.py`
- `portfolio/storage.py`

关键字段：

| 字段 | 含义 |
|---|---|
| `order_id` | 订单 ID |
| `trade_date` | 模拟交易日 |
| `stock_code` / `stock_name` | 股票代码和名称 |
| `action` | 内部动作，通常为 `buy`、`sell`、`reduce` |
| `paper_action` | 页面展示动作，如 `paper_buy`、`paper_sell`、`paper_reduce` |
| `target_weight` | 目标仓位 |
| `executed_price` | 成交价，当前默认使用收盘价 |
| `quantity` | 成交数量 |
| `gross_amount` / `order_amount` | 成交金额 |
| `commission_fee` / `slippage_cost` / `total_fee` | 成本字段 |
| `net_cash_change` | 现金变化 |
| `reason` | 生成订单原因 |
| `run_id` / `execution_source` | 回放或调度来源 |

## ai_paper_decisions_latest.json

核心路径：`outputs/portfolio/<user_id>/ai_paper_decisions_latest.json`

生成位置：

- `pipelines/paper_trading_pipeline.py`
- `portfolio/storage.py`

关键字段：

| 字段 | 含义 |
|---|---|
| `decision_id` | 决策 ID |
| `trade_date` / `decision_time` | 决策日期和时间 |
| `stock_code` / `stock_name` | 股票代码和名称 |
| `paper_action` | 模拟盘动作 |
| `target_weight` / `current_weight` | 目标仓位和当前仓位 |
| `order_quantity` / `executed_price` | 计划成交数量和价格 |
| `original_rank` / `original_score` | 原始排名和分数 |
| `news_adjustment` / `user_adjustment` | 调整分量 |
| `combined_adjustment` | 综合调整 |
| `position_adjustment_ratio` | 仓位调整倍数 |
| `reason` | 决策原因 |

## 新闻映射结果

核心路径：

- `outputs/news_stock_mapping_YYYYMMDD.csv`
- `data/news_mapping.db`

生成位置：

- `news_mapping/mapping_pipeline.py`
- `news_mapping/mapping_store.py`
- `news_mapping/schema.py`

关键字段：

| 字段 | 含义 |
|---|---|
| `date` / `publish_time` | 新闻日期和发布时间 |
| `news_id` | 新闻 ID |
| `title` | 标题 |
| `source` | 来源 |
| `code` / `name` | 映射股票 |
| `link_type` | 映射类型，如公司直连、概念、产业链 |
| `confidence` | 映射置信度 |
| `reason` / `evidence` | 映射原因和证据 |
| `mapper` | 规则、概念或 LLM 映射器 |
| `status` | `auto_confirmed`、`pending_review`、`manual_confirmed` 等 |
