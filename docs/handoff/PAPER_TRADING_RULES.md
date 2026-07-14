# Paper Trading Rules

本文档说明当前 AI 模拟盘和历史回放的交易规则。它只描述 paper trading，不代表真实交易规则。

## 核心边界

- 不连接券商。
- 不真实下单。
- 不承诺收益。
- 只基于本地 ranking、AI 调整、用户画像、现金和历史价格生成模拟账户变化。

实现位置：

- `portfolio/schemas.py`
- `portfolio/paper_trading_engine.py`
- `portfolio/storage.py`
- `pipelines/paper_trading_pipeline.py`

## 执行顺序

每日模拟盘流程：

```text
读取最终推荐
    -> 读取账户和持仓
    -> 应用到期资金流水
    -> 构建调仓计划
    -> 先卖出/减仓，再买入
    -> 更新账户、持仓、订单、净值和风险报告
    -> 写 latest 与 history 快照
```

实现位置：

- `pipelines/paper_trading_pipeline.py`
- `portfolio/cash_flow.py`
- `portfolio/rebalance_rules.py`
- `portfolio/paper_trading_engine.py`
- `portfolio/storage.py`

## 价格类型

当前默认成交价使用 `close` / `current_price`。设置字段为 `execution_price_type="close"`。

如果价格缺失或小于等于 0：

- 不生成真实订单。
- 决策可能记录为 hold 或不能执行原因。
- 账户历史快照写入前会做价格和资产一致性检查。

实现位置：

- `portfolio/trading_cost_config.py`
- `portfolio/paper_trading_engine.py`：`_decision_price(...)`
- `portfolio/storage.py`：`write_daily_snapshot(...)`

## T+1 和同日交易

当前模拟盘是日频纸面撮合，并没有完整实现真实市场 T+1 卖出限制。代码会通过持仓天数和最小持有期降低过度卖出：

- `minimum_holding_days` 在调仓计划中限制过短持有期卖出。
- 如果排名跌出缓冲区，仍可能触发退出。
- 历史回放按交易日推进，不使用未来 ranking。

实现位置：

- `portfolio/rebalance_rules.py`
- `pipelines/paper_trading_pipeline.py`：`_position_holding_days(...)`
- `pipelines/paper_backfill_pipeline.py`

## 涨跌停、停牌和缺价

当前没有完整交易所级别的涨跌停撮合引擎。

现有处理：

- `is_tradable=False` 或 `price_valid=False` 会被 hard block。
- 价格无效不会生成真实订单。
- 回放中缺预测或价格不完整时，会进入保守延续或失败延续快照。

实现位置：

- `portfolio/rebalance_rules.py`：`_hard_block(...)`
- `portfolio/paper_trading_engine.py`
- `pipelines/historical_account_replayer.py`
- `pipelines/daily_result_source_audit.py`

## 成本和滑点

默认成本：

- 买入费率：`0.0003`
- 卖出费率：`0.0008`
- 最低费用：`0`
- 滑点：`0`

费用会影响现金变化和累计费用：

```text
buy:  net_cash_change = -(gross_amount + total_fee)
sell: net_cash_change = gross_amount - total_fee
```

实现位置：

- `portfolio/trading_cost_config.py`
- `portfolio/paper_trading_engine.py`
- `portfolio/performance_metrics.py`

## 一手约束

默认一手为 100 股。买入数量按一手向下取整，现金不足时继续减少一手，直到可以买或归零。

实现位置：

- `portfolio/target_weight_allocator.py`
- `portfolio/hierarchical_top10_allocator.py`
- `portfolio/paper_trading_engine.py`

## 初始资产

初始资产来源优先级：

1. 用户画像中的 `available_capital`。
2. 用户画像中的 `initial_cash`。
3. `config.DEFAULT_INITIAL_CASH`。
4. 兜底 `100000.0`。

前端设置位置：

- AI 模拟盘页面的“用户画像与初始资产”表单。

实现位置：

- `app/pages/ai_paper_trading.py`
- `app/classic_services.py`
- `pipelines/paper_trading_pipeline.py`：`_initial_cash_from_user_profile(...)`
- `portfolio/paper_account.py`：`create_default_account(...)`
- `config.py`

## 历史回放

默认开始日：`2026-04-01`

前端点击“重新执行历史回放”会：

- 备份旧结果。
- `resume=False`。
- `force=True`。
- `skip_news=True`。
- 从选择日期重新生成账户、持仓、订单、净值和审计。

实现位置：

- `app/pages/ai_paper_trading.py`
- `pipelines/paper_backfill_pipeline.py`
- `pipelines/backfill_state.py`
- `pipelines/historical_account_audit.py`
- `portfolio/storage.py`

## 历史成分股、复权、分红和退市

当前系统的历史回放主要依赖已保存的历史 ranking 和当时的价格字段，不完整追溯历史指数成分、分红、复权和退市事件。

现有规则：

- 历史 ranking 是回放主输入，不能用最新 ranking 代替缺失历史日期。
- 缺失 ranking 的交易日会被跳过或保守延续。
- `current_price` / `close` 是模拟成交和 mark-to-market 的主要价格。

实现位置：

- `pipelines/historical_prediction_loader.py`
- `pipelines/paper_backfill_pipeline.py`
- `pipelines/historical_account_replayer.py`
- `portfolio/performance_metrics.py`

## latest 和 history

模拟盘同时保存当前状态和历史快照：

- `paper_account_latest.json`：当前账户。
- `paper_positions_latest.csv`：当前持仓。
- `paper_orders_latest.csv`：最近一次执行产生的真实订单。
- `paper_nav_latest.csv`：净值历史序列。
- `history/accounts/`：每日账户快照。
- `history/positions/`：每日持仓快照。
- `history/orders/`：每日订单快照。
- `history/nav/`：每日净值快照。
- `history/decisions/`：每日决策快照。

实现位置：

- `portfolio/storage.py`

