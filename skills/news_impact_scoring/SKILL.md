# News Impact Scoring

## Purpose

评估已映射新闻对候选股票的方向、强度、置信度和风险提示，回答“新闻事件是否带来风险”。

## Input

- `news_id`
- `stock_code`
- `event_type`
- `sentiment`
- `impact_direction`
- `impact_strength`
- `impact_confidence`
- `mapping_confidence`
- `evidence_text`

## Process

1. 先检查映射置信度，低置信新闻不能强行影响个股。
2. 基于方向、强度和置信度生成 `news_score`。
3. 对重大负面、处罚、事故、监管、业绩下修等事件输出明确风险提示。
4. 新闻分数必须受限，不能覆盖 K 线模型预测。
5. 输出证据和原因，供后续融合和日志审计。

## Output Schema

```python
NewsImpactScoringOutput(
    news_id: str,
    stock_code: str,
    news_score: float,
    impact_direction: str,
    risk_warning: str,
    confidence: float,
    reason: str,
    evidence_text: str,
    metadata: dict,
)
```

## Constraints

- `news_score` 建议限制在 `[-0.3, 0.3]` 附近。
- BM25、Dense、Rerank 分数只表示相关性，不能当作新闻影响分数。
- 不能只根据一条新闻直接改写模型预测。
- 必须服务四个核心问题：用户是否适合、模型预测是否可靠、新闻事件是否带来风险、Agent 修改是否有效。

## Examples

输入：重大处罚新闻，映射置信度 0.86。  
输出：`news_score=-0.25`，`impact_direction="negative"`，`risk_warning` 说明处罚风险，并引用证据句。
