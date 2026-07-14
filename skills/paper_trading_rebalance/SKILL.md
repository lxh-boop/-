# Paper Trading Rebalance

## Purpose

把融合后的候选信号转成模拟盘目标仓位和模拟订单，用于验证 Agent 修改是否有效。

## Input

- `user_id`
- `trade_date`
- `cash`
- `positions`
- `fused_signals`
- `constraints`

## Process

1. 仅处理 `paper trading`，不生成实盘下单指令。
2. 根据 `final_score`、`action`、用户约束和仓位限制生成目标权重。
3. 检查单股仓位、行业仓位和现金约束。
4. 对剔除、降权、观察等动作分别生成模拟订单或不交易说明。
5. 输出可供后续回测和 `backtest_evaluation` 使用的记录。

## Output Schema

```python
PaperTradingRebalanceOutput(
    user_id: str,
    trade_date: str,
    target_weights: list[dict],
    paper_orders: list[dict],
    risk_summary: dict,
    reason: str,
    metadata: dict,
)
```

## Constraints

- 明确是模拟盘，不允许自动实盘交易。
- 不能忽略用户风险等级和持仓集中度。
- 所有调仓依据必须能追溯到模型预测、新闻证据或用户约束。
- 必须服务四个核心问题：用户是否适合、模型预测是否可靠、新闻事件是否带来风险、Agent 修改是否有效。

## Examples

输入：某候选股票动作是 `exclude`，原有模拟持仓中存在该股票。  
输出：生成模拟卖出订单，并在原因中记录触发的风险规则和证据 ID。
