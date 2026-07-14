# Recommendation Explanation

## Purpose

为最终后处理结果生成可读解释，说明模型依据、新闻证据、用户适当性和风险提示。

## Input

- `user_id`
- `trade_date`
- `stock_code`
- `action`
- `final_score`
- `model_reason`
- `news_reason`
- `user_reason`
- `evidence`

## Process

1. 按“模型预测、新闻风险、用户适当性、Agent 后处理动作”组织解释。
2. 引用外层传入的证据摘要和 chunk ID，不编造证据。
3. 使用非确定性、非荐股表达。
4. 保留免责声明。
5. 说明该动作未来应通过 `agent_decision_log` 和 `backtest_evaluation` 检查是否有效。

## Output Schema

```python
RecommendationExplanationOutput(
    stock_code: str,
    action: str,
    explanation: str,
    evidence_summary: list[str],
    risk_warning: str,
    disclaimer: str,
    metadata: dict,
)
```

## Constraints

- 不输出“建议买入”“建议卖出”“目标价”“保证收益”等表达。
- 不能使用未提供的新闻或未来新闻。
- 解释必须能追溯证据来源。
- 必须服务四个核心问题：用户是否适合、模型预测是否可靠、新闻事件是否带来风险、Agent 修改是否有效。

## Examples

输入：动作 `down_weight`，原因包括模型低置信和负面公告。  
输出：解释为“该候选仅适合观察或降低展示权重”，列出负面公告证据和模型不确定性。
