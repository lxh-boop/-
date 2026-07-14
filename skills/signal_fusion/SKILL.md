# Signal Fusion

## Purpose

融合 K 线模型、新闻影响、用户偏好、风险惩罚和持仓集中度，生成标准后处理动作，连接“模型预测是否可靠”“新闻事件是否带来风险”“用户是否适合”。

## Input

- `stock_code`
- `trade_date`
- `kline_score`
- `model_confidence_score`
- `news_score`
- `user_preference_score`
- `risk_penalty`
- `concentration_penalty`
- `weights`

## Process

1. 使用规则公式计算最终分数：
   `final_score = kline_score*w1 + news_score*w2 + user_preference_score*w3 - risk_penalty*w4 - concentration_penalty*w5`。
2. 根据最终分数和硬约束输出动作：保留、降权、剔除、加入观察、风险提示。
3. 对低置信模型、高风险新闻、用户不适配和行业集中分别记录触发原因。
4. 生成可写入 `agent_decision_log` 的原因和证据 ID。

## Output Schema

```python
SignalFusionOutput(
    stock_code: str,
    trade_date: str,
    kline_score: float,
    news_score: float,
    risk_penalty: float,
    final_score: float,
    action: str,
    target_weight: float,
    reason: str,
    risk_warning: str,
    metadata: dict,
)
```

## Constraints

- 新闻分数不能完全覆盖 K 线模型。
- 输出动作必须属于标准动作集合，不能输出实盘下单指令。
- Agent 修改必须能被后续回测评估是否有效。
- 必须服务四个核心问题：用户是否适合、模型预测是否可靠、新闻事件是否带来风险、Agent 修改是否有效。

## Examples

输入：K 线分数较高、模型置信中等，但重大负面新闻触发高风险。  
输出：`action="down_weight"` 或 `action="watch"`，说明新闻风险和模型不确定性。
