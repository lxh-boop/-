# Kline Prediction Interpretation

## Purpose

解释 K 线/量价模型输出的预测分数、排名、可信度和不确定性，回答“模型预测是否可靠”。

## Input

- `trade_date`
- `stock_code`
- `stock_name`
- `model_name`
- `pred_score`
- `pred_rank`
- `pred_return`
- `confidence`
- `risk_score`
- `feature_summary`

## Process

1. 读取外层传入的 `model_prediction` 结果，不重新预测。
2. 解释预测排名、分数、可信度和风险分数。
3. 标记低置信、异常高分、行业集中或数据缺失等不可靠情形。
4. 生成中性解释，不输出确定性涨跌判断。
5. 将解释结果交给 signal fusion 或 recommendation explanation 使用。

## Output Schema

```python
KlinePredictionInterpretationOutput(
    stock_code: str,
    model_reliability: str,
    reliability_score: float,
    key_factors: list[str],
    uncertainty: str,
    reason: str,
    metadata: dict,
)
```

## Constraints

- Skill 不直接查数据库、不调 API、不跑模型。
- Agent 不能重新预测股票涨跌，只能解释外层传入的预测结果。
- 不能使用“必涨”“确定上涨”等表达。
- 必须服务四个核心问题：用户是否适合、模型预测是否可靠、新闻事件是否带来风险、Agent 修改是否有效。

## Examples

输入：模型排名靠前但 `confidence="low"`。  
输出：模型可靠性为低，原因是预测置信度不足，建议后续只作为观察候选进入融合层。
