# Skills

`skills/` 定义金融 Agent 的标准任务方法、输入输出 schema 和约束。Skill 本身不直接查数据库、不调用 API、不跑模型；它描述“该怎么做”，由 Pipeline、Tool 或 Agent 在外层负责数据读取、模型调用和落库。

所有 Skill 必须围绕数据库设计中的四个核心问题：

- 用户是否适合
- 模型预测是否可靠
- 新闻事件是否带来风险
- Agent 修改是否有效

## 当前 Skill 清单

| Skill | 作用 |
|---|---|
| `news_event_extraction` | 从新闻、公告、政策文本中抽取结构化事件 |
| `news_stock_mapping` | 将事件映射到股票、行业或概念，并给出映射置信度 |
| `news_impact_scoring` | 评估新闻对候选股票的方向、强度和风险 |
| `kline_prediction_interpretation` | 解释 K 线模型预测结果和可靠性 |
| `signal_fusion` | 融合模型、新闻、用户和风险约束生成后处理动作 |
| `user_profile_adaptation` | 判断候选资产是否适合当前用户画像 |
| `paper_trading_rebalance` | 生成模拟盘调仓目标和订单建议 |
| `recommendation_explanation` | 生成带证据来源和免责声明的解释 |
| `compliance_risk_control` | 检查输出是否合规、是否越过投资建议边界 |

## 约束

- Skill 输出只能使用标准动作：保留、降权、剔除、加入观察、风险提示、仅解释、不调整。
- RAG 检索分数只代表相关性，不能当作利好利空或投资信号。
- Agent 不能重新预测涨跌，只能基于 `model_prediction` 做后处理。
- 每次 Agent 后处理必须由外层写入 `agent_decision_log`，并保留证据快照。

免责声明：本项目仅用于机器学习研究、金融数据分析、量化策略验证、模拟盘展示和项目作品集展示。不构成投资建议，不承诺收益，不用于实盘自动交易。
