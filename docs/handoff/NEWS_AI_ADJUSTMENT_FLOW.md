# News And AI Adjustment Flow

本文档说明新闻、RAG、AI 调整、可靠度和历史回放的关系。

## 总流程

```text
模型排名
    -> 新闻/公告缓存
    -> 股票映射
    -> RAG 检索证据
    -> 新闻影响分数
    -> 用户画像适配
    -> AI 可靠度加权
    -> final_recommendations
    -> paper trading
```

实现位置：

- `pipelines/daily_update_pipeline.py`
- `pipelines/prediction_pipeline.py`
- `pipelines/rag_pipeline.py`
- `pipelines/signal_fusion_pipeline.py`
- `scoring/final_score.py`
- `scoring/signal_fusion.py`

## 新闻来源

当前新闻/公告来源以本地缓存和 Tushare/测试缓存为主。

常见产物：

- `data/news_cache.csv`
- `data/announcement_cache.csv`
- `data/news_mapping.db`
- `outputs/news_stock_mapping_YYYYMMDD.csv`
- `outputs/news_event_features_YYYYMMDD.csv`
- `outputs/news_api_test/*.csv`

AkShare fallback:
- `news_data.py` tries Tushare first; when Tushare returns no rows or has no permission, it can fall back to AkShare if `config.ENABLE_AKSHARE_NEWS_FALLBACK=True`.
- AkShare announcement source: `ak.stock_notice_report(...)`, cached into `data/announcement_cache.csv`.
- AkShare stock news source: `ak.stock_news_em(...)`, cached into `data/news_cache.csv`.
- Config knobs: `AKSHARE_FETCH_ANNOUNCEMENTS`, `AKSHARE_FETCH_STOCK_NEWS`, `AKSHARE_NOTICE_RECENT_PAGES`, `AKSHARE_NOTICE_MAX_DAYS`, `AKSHARE_STOCK_NEWS_MAX_CODES`, `AKSHARE_REQUEST_SLEEP_SECONDS`.

实现位置：

- `news_data.py`
- `news_features.py`
- `news_mapping/news_ingestor.py`
- `news_mapping/mapping_pipeline.py`
- `news_mapping/schema.py`

## 去重和映射

新闻先入库，再映射到股票。

映射方式：

- 规则别名：股票简称、公司名、代码命中。
- 概念映射：概念、行业、产业链映射到多只股票。
- LLM 映射：可选，用于复杂新闻。

状态规则：

- 直接规则命中通常 `auto_confirmed`。
- 置信度 `>=0.85` 自动确认。
- 置信度 `>=0.60` 进入 `pending_review`。
- 更低置信度不保存为有效映射。

实现位置：

- `news_mapping/entity_extractor.py`
- `news_mapping/concept_mapper.py`
- `news_mapping/llm_mapper.py`
- `news_mapping/mapping_store.py`

## 多股票新闻

同一条新闻可以映射到多只股票。每个映射包含独立字段：

- `code`
- `name`
- `link_type`
- `confidence`
- `reason`
- `evidence`
- `mapper`
- `status`

下游计算时按股票聚合新闻证据。

实现位置：

- `news_mapping/mapping_store.py`
- `scoring/final_score.py`：`_group_news(...)`
- `pipelines/historical_news_loader.py`

## 新闻调整分数

新闻调整由 `calculate_news_adjustment(...)` 计算。

过滤规则：

- 发布时间晚于交易日，不使用。
- 交易日当天 15:00 之后发布，不用于当天决策。
- 影响置信度或映射置信度低于 `0.40`，忽略。

计算规则：

```text
raw = 0.30 * direction_weight * strength * impact_confidence * mapping_confidence * max(0.50, importance)
news_adjustment = clamp(sum(raw), -0.30, 0.30)
```

实现位置：

- `scoring/news_adjustment.py`
- `scoring/schemas.py`：`NewsEvidenceSignal`

## AI 调整聚合

每只股票的最终调整：

```text
effective_news_adjustment = ai_reliability_weight * news_adjustment
combined_adjustment = effective_news_adjustment + user_adjustment
position_adjustment_ratio = clamp(1 + combined_adjustment, 0, 2)
```

如果没有新闻，`news_adjustment=0`，新闻项保持中性。冷启动时 `ai_reliability_weight=0`，即使有新闻，新闻也不会实际改变仓位。

实现位置：

- `scoring/signal_fusion.py`
- `scoring/final_score.py`
- `evaluation/reliability_updater.py`

## LLM 失败和无新闻行为

- RAG 搜索失败：记录错误，尽量返回空证据，不中断主流程。
- LLM 映射失败：规则和概念映射仍可工作。
- 无新闻：输出 `No usable news evidence.`，仓位调整由用户画像和原始目标仓位决定。
- 历史回放前端当前默认 `skip_news=True`，因此从 `2026-04-01` 重放时不会重新抓新闻。

实现位置：

- `pipelines/rag_pipeline.py`
- `news_mapping/mapping_pipeline.py`
- `pipelines/paper_backfill_pipeline.py`
- `app/pages/ai_paper_trading.py`

## 可靠度更新

AI 可靠度来自历史调整效果评估。样本不足 `20` 条时为冷启动。

输出状态包括：

- `ai_reliability_weight`
- `recent_hit_rate`
- `recent_adjustment_alpha`
- `recent_avoided_loss`
- `recent_missed_gain`
- `recent_ai_adjustment_score`
- `status`

实现位置：

- `evaluation/ai_adjustment_evaluator.py`
- `evaluation/evaluation_pipeline.py`
- `evaluation/evaluation_store.py`
- `evaluation/reliability_updater.py`

## 历史回放 skip_news

AI 模拟盘页面点击“重新执行历史回放”时，当前参数为：

```text
resume=False
force=True
skip_news=True
strategy=hierarchical_top10
top_k=15
entry_top_k=10
hold_buffer_rank=15
max_positions=10
```

这意味着历史回放优先复用历史 ranking 和已有 AI 调整，或在缺新闻模式下生成中性新闻调整，不重新联网补新闻。

实现位置：

- `app/pages/ai_paper_trading.py`
- `pipelines/paper_backfill_pipeline.py`
- `pipelines/historical_prediction_loader.py`
- `pipelines/historical_ai_adjustment_loader.py`
- `pipelines/historical_news_loader.py`
