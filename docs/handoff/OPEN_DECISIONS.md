# Open Decisions

本文档记录当前尚未完全闭合的业务口径。它不是实现说明，而是给产品/业务/后续开发需要最终拍板的问题清单。每个问题都列出当前代码行为、未决点、建议决策和涉及文件。

## 1. Top10 80% + 现金 5% 之后的剩余 15%

当前已明确：

- Top10 目标总仓位是 `80%`。
- 目标现金比例是 `5%`。
- 两者合计为 `85%`。

当前代码行为：

- `portfolio/hierarchical_top10_allocator.py` 中 `TOP10_TARGET_RATIO = 0.80`。
- `portfolio/trading_cost_config.py` 中 `target_cash_ratio/minimum_cash_ratio` 默认是 `0.05`。
- `portfolio/rebalance_rules.py` 中 Top11-15 缓冲持仓还有独立上限：单只 `10%`、桶总计 `15%`。
- 如果 Top11-15 没有旧持仓，剩余 15% 不会被强制分配，实际会成为现金或无法分配仓位。

尚未确定：

- 剩余 15% 是明确保留给 Top11-15 原持仓，还是额外现金/风险缓冲。
- 如果 Top11-15 没有旧持仓，是否允许 Top10 使用到 95%。
- 当前“现金 5% + Top11-15 最高 15% + Top10 80%”是否就是最终组合设计。

建议拍板选项：

1. 推荐：定义为“Top11-15 旧持仓缓冲上限 15%，没有缓冲持仓时不强制使用，未使用部分留作现金/风险缓冲”。
2. 备选：Top10 目标总仓位改为 95%，Top11-15 只作为卖出缓冲，不占独立目标仓位。
3. 备选：现金目标从 5% 改为 20%，Top11-15 不单独占仓。

涉及文件：

- `portfolio/hierarchical_top10_allocator.py`
- `portfolio/rebalance_rules.py`
- `portfolio/trading_cost_config.py`
- `app/pages/ai_paper_trading.py`
- `CORE_BUSINESS_RULES.md`
- `PAPER_TRADING_RULES.md`

## 2. Top11-15 持仓如何占用仓位

当前已明确：

- Top11-15 只能保留已有持仓。
- Top11-15 不能新买。
- Top15 以外原则上退出。

当前代码行为：

- `portfolio/rebalance_rules.py` 的 `_buffer_targets(...)` 会给 Top11-15 的已有持仓设置目标仓位。
- Top11-15 单只目标仓位取 `min(当前仓位, 10%)`。
- Top11-15 缓冲桶总计超过 `15%` 时，会从排名更差的持仓开始压缩。
- 新进入 Top10 的股票会按 Top10 分配器生成目标仓位，但如果最大持仓数、现金、一手约束或持仓缓冲导致空间不足，最终执行可能受限。

尚未确定：

- Top11-15 缓冲持仓是否应维持原仓位，还是逐步减仓。
- Top11-15 的 15% 是否独立于 Top10 的 80%，还是应该从 Top10 80% 中扣除。
- 当已有 10 只持仓都落在 Top11-15 时，新 Top10 股票是否必须优先进入。
- 最大持仓 10 只时，是优先保留旧持仓，还是优先替换成当前 Top10。
- Top11-15 缓冲持仓是否应设置最长缓冲天数。

建议拍板选项：

1. 推荐：Top11-15 是“最多 15% 的独立旧持仓缓冲桶”，按当前仓位和上限逐步压缩；新 Top10 优先级高于缓冲持仓，但必须满足一手和现金约束。
2. 备选：Top11-15 只允许持有 1 到 3 天，之后强制退出。
3. 备选：最大持仓 10 只时，Top10 必须替换所有缓冲持仓，不保留 Top11-15。

涉及文件：

- `portfolio/rebalance_rules.py`
- `portfolio/hierarchical_top10_allocator.py`
- `portfolio/paper_trading_engine.py`
- `pipelines/paper_trading_pipeline.py`
- `pipelines/paper_backfill_pipeline.py`

## 3. 信号日与成交日

当前已明确：

- 页面说明“收盘后生成信号，以 T+1 单日收益评估”。
- 排名文件有 `date` 和可推导的 `prediction_date`。
- 模拟盘成交价当前使用 `close/current_price`。

当前代码行为：

- `app.py` 会把 `date` 推导成下一交易日 `prediction_date`。
- `portfolio/paper_trading_engine.py` 使用调仓决策里的 `current_price` 或 `close` 作为成交价。
- 历史回放中，`pipelines/historical_prediction_loader.py` 按 `trade_date` 加载当天历史 ranking，`pipelines/paper_backfill_pipeline.py` 以 `decision_time=f"{trade_date} 15:00:00"` 执行当日模拟。
- 因此当前历史回放更接近“T 日排名/价格在 T 日 15:00 决策并用 T 日 close 成交”的纸面撮合，而首页说明又偏向“T 日收盘后预测 T+1”。

尚未确定：

- 最终业务口径究竟是：
  - T 日收盘后生成排名，T+1 日收盘成交；
  - 还是 T 日盘前已有排名，T 日收盘成交；
  - 还是仅做 T 日收盘价纸面回放，不宣称可执行成交。
- 历史回放是否需要整体 shift 一天，避免同日收盘价不可执行的问题。
- `trade_date` 在 ranking、recommendations、orders 中应表示信号日还是成交日。

建议拍板选项：

1. 推荐：统一为“T 日收盘后生成信号，T+1 日按收盘价模拟成交；T 日信号用 T+1 单日收益评估”。这更符合可执行性，也与首页 T+1 回测说明一致。
2. 短期兼容：文档明确当前历史回放是“T 日收盘价纸面撮合”，仅用于策略结构验证，不宣称真实可执行。
3. 若选择推荐方案，需要调整历史回放的价格对齐、订单日期和审计字段。

涉及文件：

- `app.py`
- `daily_incremental_update.py`
- `pipelines/historical_prediction_loader.py`
- `pipelines/paper_backfill_pipeline.py`
- `portfolio/paper_trading_engine.py`
- `portfolio/rebalance_rules.py`
- `PAPER_TRADING_RULES.md`
- `MODEL_SPECIFICATION.md`

## 4. AI 可靠度在 0.40 到 0.60 之间如何更新

当前已明确：

- 最近 AI 调整评分 `>= 0.60` 时提高可靠度。
- 最近 AI 调整评分 `< 0.40` 时目标可靠度归零。
- 样本不足 20 条时冷启动为 0。

当前代码行为：

- `evaluation/reliability_updater.py` 中 `[0.40, 0.60)` 区间的 `target_weight = old_weight`。
- 新权重仍通过平滑公式计算：`0.8 * old_weight + 0.2 * target_weight`。
- 因为 `target_weight=old_weight`，所以最终等于保持不变。

尚未确定：

- `[0.40, 0.60)` 是否应保持不变。
- 是否应缓慢衰减，例如每次乘以 `0.95`。
- 是否应回到中性权重，例如逐步回归 `0.50`。
- 是否需要区分 0.40-0.50 和 0.50-0.60。

建议拍板选项：

1. 推荐：维持当前实现，定义为“中性区间，可靠度保持不变”。
2. 备选：中性偏弱区间缓慢衰减，避免长期锁定旧高权重。
3. 备选：评分连续多期处于中性区间才衰减。

涉及文件：

- `evaluation/reliability_updater.py`
- `evaluation/evaluation_store.py`
- `CORE_BUSINESS_RULES.md`
- `NEWS_AI_ADJUSTMENT_FLOW.md`

## 5. 新闻映射阈值和 pending_review 是否参与自动调整

当前已明确：

- 新闻映射保存层：
  - `>=0.85` 自动确认。
  - `>=0.60` 待审核。
  - 更低置信度不保存为有效映射。
- 新闻评分层：
  - `impact_confidence < 0.40` 或 `mapping_confidence < 0.40` 时忽略。

当前代码行为：

- `news_mapping/mapping_store.py` 中低于 `0.60` 的映射通常不会保存为有效链接。
- `news_mapping/mapping_pipeline.py` 导出事件特征时会纳入 `auto_confirmed`、`manual_confirmed`、`pending_review`。
- `scoring/news_adjustment.py` 只看 `impact_confidence` 和 `mapping_confidence` 的 `0.40` 阈值，不直接检查 `status`。
- `pipelines/historical_news_loader.py` 从 repository 加载新闻映射时，没有在该层明确只允许 confirmed 状态。
- 因此当前“pending_review 是否参与自动仓位调整”的口径没有完全闭合，取决于上游 repository 返回的数据和字段。

尚未确定：

- `pending_review` 是否能参与自动仓位调整。
- 0.40 到 0.60 的映射是否理论上可能进入评分，还是保存层已完全阻止。
- 手工确认 `manual_confirmed` 是否总是优先参与。
- LLM 映射和规则映射是否应使用同一阈值。

建议拍板选项：

1. 推荐：自动仓位调整只使用 `auto_confirmed` 和 `manual_confirmed`；`pending_review` 只展示和进入人工审核，不参与仓位。
2. 备选：`pending_review` 允许参与，但新闻影响强度额外打折，例如乘以 `0.5`。
3. 备选：保留当前按置信度数值过滤，但文档明确 pending_review 可能参与。

如果选择推荐方案，需要在新闻证据加载层显式过滤状态，而不只依赖导出或保存层。

涉及文件：

- `news_mapping/mapping_store.py`
- `news_mapping/mapping_pipeline.py`
- `database/repositories/news_repository.py`
- `pipelines/historical_news_loader.py`
- `pipelines/rag_pipeline.py`
- `scoring/news_adjustment.py`
- `NEWS_AI_ADJUSTMENT_FLOW.md`

## 建议处理顺序

1. 先确定信号日和成交日，因为它影响回放、收益评估和所有订单日期。
2. 再确定剩余 15% 和 Top11-15 缓冲桶，因为它影响组合目标仓位。
3. 再确定新闻 pending_review 参与规则，因为它影响 AI 调整是否自动触发。
4. 最后确定可靠度中性区间，因为当前实现已经可解释为“保持不变”。

