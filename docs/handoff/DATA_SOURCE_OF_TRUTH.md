# Data Source Of Truth

本文档说明 CSV、JSON、SQLite、缓存、latest 和 history 同时存在时，接手者应该以哪里为准。

## 总原则

- 页面展示优先读 `latest` 文件。
- 历史回放必须读 `history` 或数据库中的对应日期，不允许用最新文件补历史。
- SQLite 是结构化存储和 Agent/调度的长期方向，但当前 APP 仍有大量 CSV/JSON fallback。
- 若 CSV/JSON 与 SQLite 冲突，先看当前页面或 pipeline 实际读取路径。

## 每日预测排名

当前展示权威：

```text
outputs/ranking_latest.csv
```

历史回放权威：

```text
outputs/rankings/history/ranking_YYYYMMDD.csv
outputs/portfolio/<user_id>/history/rankings/ranking_YYYYMMDD.csv
```

数据库备选：

```text
database.model_prediction
```

实现位置：

- `app.py`：`load_ranking()`
- `pipelines/prediction_pipeline.py`
- `pipelines/historical_prediction_loader.py`
- `database/repositories/prediction_repository.py`

## AI 调整结果

当前用户级权威：

```text
outputs/users/<user_id>/recommendations/final_recommendations_latest.csv
outputs/users/<user_id>/recommendations/final_recommendations_YYYYMMDD.csv
```

历史回放读取候选：

```text
outputs/users/<user_id>/recommendations/final_recommendations_YYYYMMDD.csv
outputs/recommendations/history/final_recommendations_YYYYMMDD.csv
outputs/recommendations/final_recommendations_YYYYMMDD.csv
```

实现位置：

- `scoring/final_score.py`
- `pipelines/historical_ai_adjustment_loader.py`
- `app/classic_services.py`

## 模拟盘账户、持仓和订单

当前页面展示优先：

```text
outputs/portfolio/<user_id>/paper_account_latest.json
outputs/portfolio/<user_id>/paper_positions_latest.csv
outputs/portfolio/<user_id>/paper_orders_latest.csv
outputs/portfolio/<user_id>/paper_nav_latest.csv
```

历史查看和回放审计：

```text
outputs/portfolio/<user_id>/history/accounts/
outputs/portfolio/<user_id>/history/positions/
outputs/portfolio/<user_id>/history/orders/
outputs/portfolio/<user_id>/history/nav/
outputs/portfolio/<user_id>/history/decisions/
runtime/replay_audit/<user_id>/<run_id>/
```

数据库镜像：

```text
paper_account
portfolio_position
paper_order
paper_decision_log
paper_nav_history
```

实现位置：

- `portfolio/storage.py`
- `portfolio/paper_account.py`
- `database/repositories/portfolio_repository.py`
- `app/pages/ai_paper_trading.py`

## 用户画像和初始资产

优先级：

1. SQLite 用户表。
2. `outputs/users/<user_id>/user_profile.json`。
3. 旧兼容路径 `outputs/portfolio/<user_id>/user_context.json`。
4. 默认配置。

实现位置：

- `app/classic_services.py`
- `portfolio/user_profile.py`
- `database/repositories/user_repository.py`
- `config.py`

## 行情和特征缓存

训练缓存：

```text
data/train_raw_stock_data.csv
data/train_feature_stock_data_alpha158.csv
```

每日更新缓存：

```text
data/latest_raw_stock_data.csv
data/latest_feature_stock_data_alpha158.csv
```

股票池缓存：

```text
data/csi300_stock_pool.csv
```

实现位置：

- `data_local.py`
- `data_tushare.py`
- `alpha158.py`
- `daily_incremental_update.py`
- `universe.py`

## 新闻和 RAG

缓存和数据库：

```text
data/news_cache.csv
data/announcement_cache.csv
data/news_mapping.db
data/rag_documents.csv
data/rag_tfidf_index.pkl
```

导出结果：

```text
outputs/news_stock_mapping_YYYYMMDD.csv
outputs/news_event_features_YYYYMMDD.csv
```

实现位置：

- `news_data.py`
- `news_features.py`
- `news_mapping/`
- `rag/`
- `pipelines/rag_pipeline.py`

## 模型

当前最佳外部模型：

```text
models/external_zoo/chronos/chronos_bolt_small/
models/external_zoo/metadata.json
```

当前模型状态、下载信息和页面排名以外部模型目录、metadata 与 `outputs/ranking_latest.csv` 为准。

实现位置：

- `model_zoo_backend.py`
- `model_zoo/registry.py`

## 冲突处理

| 冲突 | 处理 |
|---|---|
| `ranking_latest.csv` 与历史 ranking 不一致 | 首页用 latest，历史回放用 history |
| `paper_account_latest.json` 与 history 不一致 | 当前页面用 latest，历史审计用对应日期 history |
| SQLite 与 CSV/JSON 不一致 | 看当前调用的 repository 或 fallback；必要时用 `portfolio/storage.py` 重新写快照 |
| final recommendations 与 ranking 不一致 | 回放会校验原始 Top10 是否对齐，不对齐则标记 mismatch |
| 缺少某日 ranking | 不用最新 ranking 补，回放保守延续或跳过 |
