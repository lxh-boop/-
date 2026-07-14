# User Profile Adaptation

## Purpose

根据用户画像、风险测评、投资目标和持仓，判断模型候选资产是否适合当前用户，回答“用户是否适合”。

## Input

- `user_id`
- `risk_level`
- `investment_horizon`
- `liquidity_need`
- `asset_risk_level`
- `stock_code`
- `industry`
- `current_positions`

## Process

1. 比较用户风险等级和资产风险等级。
2. 检查投资期限和流动性需求是否与高波动资产冲突。
3. 检查用户当前持仓是否已经过度集中在同一股票或行业。
4. 输出适当性等级、用户偏好分和建议后处理动作。
5. 记录触发规则，供外层写入 `agent_decision_log`。

## Output Schema

```python
UserProfileAdaptationOutput(
    user_id: str,
    stock_code: str,
    is_suitable: bool,
    suitability_level: str,
    user_preference_score: float,
    action: str,
    reason: str,
    triggered_rules: list[str],
    metadata: dict,
)
```

## Constraints

- 不能绕过用户风险测评。
- C1/C2 用户不应匹配高风险高波动重仓建议。
- 输出不代表真实交易建议，只作为模拟盘和展示分析约束。
- 必须服务四个核心问题：用户是否适合、模型预测是否可靠、新闻事件是否带来风险、Agent 修改是否有效。

## Examples

输入：用户 C2、流动性需求高、候选股票波动较高。  
输出：`is_suitable=False`，`action="watch"` 或 `action="down_weight"`，原因说明风险等级和流动性不匹配。
