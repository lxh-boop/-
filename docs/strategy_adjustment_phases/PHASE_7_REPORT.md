# Phase 7 验收报告：历史保留与当前持仓独立确认

## 核心结论

已实现并验证：

```text
修改/注册策略
≠ 启用账户 Binding
≠ 立即修改当前持仓
```

三者分别使用独立计划、独立确认类型和独立提交工具。

## 新增服务与工具

- `agent/services/strategy_position_service.py`
- `strategy.preview_current_position_change`
- `strategy.position.commit`

预览工具使用当前账户有效 Binding 和同一 Runtime Resolver 生成：

- TargetPortfolio
- 买卖清单与数量
- 费用与现金变化
- 风险前后摘要
- `confirmation_required_portfolio_operation`

确认前不修改账户、持仓、订单、净值或交易设置。

提交工具会在消费确认前重新检查：

- 用户与账户作用域
- 账户现金、总资产和持仓快照哈希
- 当前 `binding_id`
- 当前 `config_hash`

检查通过后调用原 `paper_trading_pipeline`，不实现旁路交易逻辑。

## 历史保留

`paper_strategy_execution_history` 继续保存：

- `trade_date`
- `strategy_id`
- `strategy_version`
- `binding_id`
- `config_hash`
- `positions_before`
- `target_portfolio`
- `orders`
- `positions_after`
- `cash_before`
- `cash_after`

每日持仓快照、账户快照、订单、资金流水和净值文件/数据库保持原有路径。
策略 Binding 切换和回滚只新增历史事件，不删除旧 Binding 或业务历史。

## 专项测试

Phase 7 指定的 10 项测试：

```text
10 passed
```

覆盖：

- 启用策略不改当前持仓
- 历史持仓、订单、净值可查询
- 策略切换历史可见
- 预览不写业务状态
- 当前持仓变化必须独立确认
- 账户变化导致 revalidate 拒绝
- 执行保留 before snapshot
- Binding 回滚不删除历史

## 关键回归

一次性仓位操作、组合稳定性操作、原确认链、WriteGateway、历史查询、
Binding、默认 golden：

```text
36 passed
```

## 全量回归

```text
932 passed, 8 failed, 255 warnings
```

8 项均属于 Phase 0 已记录的既有失败；原基线中的一项本轮通过，没有新增
失败。

## 下一阶段入口

Phase 8 将补齐 Proposal、Implementation、Activation、Position 四类
前端卡片，隐藏 confirmation token，展示明确且不混淆的按钮文案，并完成
审计、故障降级、文档、全量测试和 8501 端口真实部署验收。

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
