# Phase 8 验收报告：前端、审计、降级与最终回归

## 用户可见闭环

`app/pages/ai_agent.py` 已按操作阶段展示四类卡片：

- Proposal 草稿：当前版本、相对当前策略变化、保留规则、预期效果、代价、
  修改历史摘要；没有正式确认按钮。
- Implementation 预览：config/composite/code 路径、正式目标、diff、安全检查、
  测试、回测和回滚；按钮为“确认应用并注册”与“拒绝”。
- Activation 预览：当前策略、新策略、生效日期、是否影响当前持仓；按钮为
  “确认启用未来策略”与“拒绝”。
- Position 预览：TargetPortfolio、买卖清单、费用、现金和风险变化；按钮为
  “确认执行模拟盘调仓”与“拒绝”。

三类正式确认文案不共用模糊的“确认执行”。技术详情和工具结果继续经过
递归脱敏，`confirmation_token`、token hash 和 plan hash 不显示。

## 审计链

新增：

- `agent/services/strategy_audit_service.py`
- 只读工具 `strategy.get_audit_trace`

可以从以下任一稳定标识开始反向关联：

```text
proposal_id
implementation_id
plan_id
commit_id
binding_id
run_id
conversation_id
```

输出包含：

- 原始请求与全部 Proposal 版本；
- 锁定版本与 Implementation；
- artifact manifest、config/code、diff、安全、测试和回测；
- 应用计划、审批、commit 与注册结果；
- 启用计划、审批、commit 与 Binding；
- 实际策略版本、resolved config、订单、持仓前后和现金前后；
- 会话消息与可用的 Agent run。

审计读取按 `user_id` 隔离。待确认文件不存在时，会从 SQLite 审计表恢复可用
摘要；确认 token 和 token hash 永不进入审计输出。

## 故障降级

最终矩阵覆盖并保持以下规则：

| 故障 | 安全结果 |
|---|---|
| LLM 无 Key、余额不足、超时、格式错误 | 保留原请求/草稿，不进入 Implementation 或正式写入 |
| 代码生成、schema、安全、接口、测试或回测失败 | Implementation 保持隔离并标记失败，不生成可提交正式版本 |
| 确认过期或 token 错误 | 不 commit，不产生半写状态 |
| 正式代码、Proposal、artifact hash 变化 | revalidate 拒绝 |
| Binding 冲突或目标变化 | 启用/回滚 commit 拒绝 |
| 当前账户或 Binding/config 变化 | 当前仓位 commit 拒绝 |
| DB/Registry/文件写失败 | 回滚新文件和 Registry，保留历史，可重新生成计划 |

这些失败都不能让规则 fallback 自动解释并实施长期策略，也不能绕过
WriteGateway、确认和重校验。

## 文档

已更新：

- `PROJECT_STRUCTURE.md`
- `PROJECT_FILE_DIRECTORY.md`
- `AGENTS.md`

并保留 D 盘虚拟环境、8501 本机端口和免责声明要求。

## 验收结果

- 编译：
  `.\.venv\Scripts\python.exe -m compileall -q agent app portfolio scoring rag pipelines database strategies scripts`
  通过。
- 所有 `test_strategy_*.py`：`35 passed`。
- Phase 8 新增 UI、审计和 LLM 降级测试：`7 passed`。
- 关键回归：`70 passed, 4 failed`；4 项为 Phase 0 既有
  Agent/多 Agent 基线失败。
- 全量：`939 passed, 8 failed, 255 warnings`；8 项全部属于 Phase 0
  既有 Agent/MCP/多 Agent/Goal Planning 基线失败，没有新增失败。
- Web：8501 健康检查为 `ok`。真实浏览器已检查首页/预测排名、AI Agent、
  AI 模拟盘的当前持仓/历史订单/每日持仓快照/组合风险，以及系统监控；
  没有 Streamlit exception 或浏览器 console error，免责声明存在，
  confirmation token 不可见。当前 live 用户没有待确认计划，四类策略卡的
  字段与三种明确确认文案由 UI/集成测试验证。

## 结论

新增策略闭环没有改变无 Binding 用户的默认 golden，没有覆盖原策略文件，
没有删除历史持仓/订单/净值，也没有合并注册、启用、当前调仓三次独立确认。

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
