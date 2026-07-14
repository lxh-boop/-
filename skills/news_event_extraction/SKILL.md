# News Event Extraction

## Purpose

从新闻、公告、政策或研报文本中抽取结构化事件，回答“新闻事件是否带来风险”的事实前置问题。

## Input

- `news_id`
- `title`
- `summary`
- `content`
- `source`
- `publish_time`
- `trade_date`
- `metadata`

## Process

1. 识别事件类型，例如业绩、政策、订单、处罚、事故、价格变化、风险提示。
2. 判断事件情绪：`positive`、`negative`、`neutral`。
3. 提取最短可审计证据句，不能只保存关键词。
4. 标记是否重大事件，并给出重要性分数。
5. 保留 `trade_date`，避免后续使用未来新闻解释过去决策。

## Output Schema

```python
NewsEventExtractionOutput(
    news_id: str,
    event_type: str,
    sentiment: str,
    importance_score: float,
    is_major_event: bool,
    evidence_text: str,
    confidence: float,
    metadata: dict,
)
```

## Constraints

- Skill 不直接查数据库、不调 API、不跑模型。
- 不根据新闻直接给出买卖结论。
- 必须保留证据文本，URL 不能替代证据。
- 必须服务四个核心问题：用户是否适合、模型预测是否可靠、新闻事件是否带来风险、Agent 修改是否有效。

## Examples

输入：某公司公告出现“业绩预告亏损扩大”。  
输出：`event_type="业绩预告"`，`sentiment="negative"`，`is_major_event=True`，证据句为公告原文中的亏损描述。
