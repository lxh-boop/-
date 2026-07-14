# Core Business Rules

本文档描述当前业务规则，不描述旧实验分支。实现文件以每节末尾为准。

## AI 仓位调整公式

当前 AI 调整不直接生成交易动作，只生成仓位调整倍数。

核心公式：

```text
effective_news_adjustment = ai_reliability_weight * news_adjustment
combined_adjustment = effective_news_adjustment + user_adjustment
position_adjustment_ratio = clamp(1 + combined_adjustment, 0, 2)
target_weight = original_target_weight * position_adjustment_ratio
```

含义：

- `news_adjustment`：新闻影响，范围 `[-0.30, 0.30]`。
- `user_adjustment`：用户画像适配，范围 `[-0.30, 0.10]`。
- `ai_reliability_weight`：AI 可靠度，范围 `[0, 1]`，冷启动为 `0`。
- `combined_adjustment`：新闻有效影响与用户影响之和。
- `position_adjustment_ratio`：最终仓位倍数，范围 `[0, 2]`。

实现位置：

- `scoring/signal_fusion.py`：`fuse_signal(...)`
- `scoring/normalizers.py`：`calculate_position_adjustment(...)`
- `scoring/news_adjustment.py`：`calculate_news_adjustment(...)`
- `scoring/user_adjustment.py`：`calculate_user_adjustment(...)`
- `evaluation/reliability_updater.py`：`update_ai_reliability_state(...)`

## 新闻调整规则

新闻证据必须满足时间和置信度要求。

- 发布时间晚于决策日，或决策日当天 15:00 之后发布的新闻，不用于当天决策。
- `impact_confidence < 0.40` 或 `mapping_confidence < 0.40` 的新闻忽略。
- 单条新闻原始影响：

```text
0.30 * direction_weight * strength * impact_confidence * mapping_confidence * max(0.50, importance)
```

- 多条新闻累加后裁剪到 `[-0.30, 0.30]`。
- 正向方向取 `+1`，负向方向取 `-1`，中性取 `0`。
- 高置信强负面新闻会标记 `major_negative=True`，但当前主公式仍以数值调整为主。

实现位置：

- `scoring/news_adjustment.py`
- `scoring/schemas.py`：`NewsEvidenceSignal`
- `news_mapping/`：新闻与股票映射。
- `pipelines/rag_pipeline.py`、`pipelines/historical_news_loader.py`：证据读取。

## 用户画像调整规则

用户画像只影响仓位倍数和目标仓位上限，不直接产生实盘动作。

- 保守型用户遇到高风险资产：`user_adjustment -= 0.25`，并标记降权原因。
- 稳健型用户遇到高风险资产：`user_adjustment -= 0.15`。
- 激进型且允许高波动时：高风险资产只小幅扣分 `-0.03`。
- 回避行业：`-0.20`，如果同时高风险再 `-0.05`。
- 偏好行业：无强制降权时 `+0.05`。
- 高流动性需求遇到高波动：`-0.10`。

单股目标上限来自用户风险等级：

- C1：`3%`
- C2：`5%`
- C3：`8%`
- C4：`10%`
- C5：`15%`

同时还会取 `user.max_single_position` 与组合约束中的较小值。

实现位置：

- `scoring/user_adjustment.py`
- `portfolio/user_profile.py`
- `app/classic_services.py`
- `app/pages/ai_paper_trading.py`

## AI 可靠度

冷启动时 `ai_reliability_weight=0`，新闻调整不会实际影响仓位。累计评估样本不足 `20` 条时仍保持冷启动。

更新规则：

- 最近 AI 调整评分 `>=0.60`：目标权重在旧权重基础上最多增加 `0.20`。
- 最近 AI 调整评分 `<0.40`：目标权重归零。
- 新权重采用平滑：`0.8 * old_weight + 0.2 * target_weight`。

实现位置：

- `evaluation/reliability_updater.py`
- `evaluation/evaluation_store.py`
- `app/pages/ai_paper_trading.py`

## 固定模拟盘策略

当前 AI 模拟盘策略写死为 `hierarchical_top10`，前端不再提供策略设置入口。

规则：

- Top1-10 是主组合候选。
- Top1-5 基础分为 `12`。
- Top6-10 基础分为 `5`。
- Top10 目标总仓位为 `80%`。
- Top11-15 是持仓缓冲区，只允许已有持仓留在缓冲区，不新买。
- Top15 之后原则上退出。
- 目标现金比例为 `5%`。
- 单股最高目标仓位为 `30%`。
- 最大持仓数为 `10`。

实现位置：

- `app/pages/ai_paper_trading.py`：`FIXED_PAPER_STRATEGY`
- `pipelines/paper_trading_pipeline.py`
- `pipelines/paper_backfill_pipeline.py`
- `portfolio/rebalance_rules.py`
- `portfolio/hierarchical_top10_allocator.py`
- `portfolio/trading_cost_config.py`

## Top10 / Top15 含义

Top10 和 Top15 都来自原始模型排名或历史 ranking，不是 AI 调整后重新排序。

- Top10：允许新买入和调仓的主组合。
- Top11-15：缓冲区，仅对已有持仓生效，减少频繁换手。
- Top15 以外：如果已有持仓，通常应卖出或减仓。

实现位置：

- `portfolio/rebalance_rules.py`：`_build_hierarchical_top10_plan(...)`
- `portfolio/hierarchical_top10_allocator.py`
- `pipelines/fixed_top10_inputs.py`
- `pipelines/historical_ai_adjustment_loader.py`

## 一手递归分配规则

A 股交易按一手约束执行，默认一手为 `100` 股。目标仓位理论上可为正，但如果现金不足以买一手，则不能生成买入订单。

当前递归处理逻辑：

1. 先按 Top10 调整分数归一化到目标仓位。
2. 检查每个候选是否买得起一手。
3. 对买不起且没有现有持仓的候选，按“排名更差、目标权重更低、分数更低”的顺序移除。
4. 每移除一个候选，就把释放的权重重新分给剩余候选。
5. 循环直到剩余候选都可执行，或没有可分配候选。
6. 之后再用剩余现金做一手一手的补充分配，但仍受现金、单股上限和总目标仓位约束。

实现位置：

- `portfolio/hierarchical_top10_allocator.py`
- `portfolio/target_weight_allocator.py`
- `portfolio/paper_trading_engine.py`
- `tests/unit/test_portfolio_allocator_executable_orders.py`

