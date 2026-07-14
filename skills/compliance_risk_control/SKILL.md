# Compliance Risk Control

## Purpose

检查 Agent、推荐解释和日报输出是否符合项目合规边界，防止变成投资建议或实盘交易指令。

## Input

- `text`
- `action`
- `evidence_ids`
- `metadata`

## Process

1. 检查是否出现“建议买入”“建议卖出”“目标价”“稳赚”“保证收益”“可以实盘”等违规表达。
2. 检查是否缺少免责声明。
3. 检查是否存在无证据推断或未来新闻解释过去决策。
4. 对违规文本生成修正文案，保留事实和风险提示。
5. 输出是否通过、违规项和需要保留的免责声明。

## Output Schema

```python
ComplianceRiskControlOutput(
    passed: bool,
    violations: list[str],
    sanitized_text: str,
    required_disclaimer: str,
    action: str,
    metadata: dict,
)
```

## Constraints

- 不能删除风险提示。
- 不能把模拟盘结果表述为真实交易收益。
- 不能允许实盘自动下单表达。
- 必须服务四个核心问题：用户是否适合、模型预测是否可靠、新闻事件是否带来风险、Agent 修改是否有效。

## Examples

输入：“建议买入某股票，目标价上涨 20%”。  
输出：`passed=False`，违规项包含确定性买入建议和目标价表达，修正文案改为项目展示和风险分析口径。
