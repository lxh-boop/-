# News Stock Mapping

## Purpose

把结构化新闻事件映射到股票、行业或概念，回答“这件事影响谁”，并为新闻风险和 Agent 后处理提供可审计依据。

## Input

- `news_id`
- `event_type`
- `evidence_text`
- `stock_candidates`
- `industry_rules`
- `metadata`

## Process

1. 优先使用直接实体命中：股票简称、公司全称、股票代码。
2. 使用行业事件规则补充行业级影响。
3. 计算 `mapping_confidence`，参考 entity、event、industry、source、position、llm 复核分和 penalty。
4. 按阈值分层：高置信可影响后处理，中等置信用于解释或观察，低置信只保留行业关系或丢弃。
5. 保留证据句，供 `agent_decision_log.evidence_snapshot` 使用。

## Output Schema

```python
NewsStockMappingOutput(
    news_id: str,
    mappings: list[{
        "stock_code": str,
        "stock_name": str,
        "industry": str,
        "concept": str,
        "relevance_score": float,
        "impact_direction": str,
        "impact_strength": float,
        "impact_confidence": float,
        "mapping_confidence": float,
        "mapping_method": str,
        "evidence_text": str,
    }],
    dropped_candidates: list,
    metadata: dict,
)
```

## Constraints

- Skill 不直接查数据库、不调 API、不跑模型。
- 不能让 LLM 全市场猜股票，只能复核候选。
- `mapping_confidence` 是映射置信度，不是买卖信号。
- 必须服务四个核心问题：用户是否适合、模型预测是否可靠、新闻事件是否带来风险、Agent 修改是否有效。

## Examples

输入：“锂价下跌，动力电池企业成本压力缓解”。  
输出：动力电池候选股票 `impact_direction="positive"`，锂矿候选股票 `impact_direction="negative"`，均带映射置信度和证据句。
