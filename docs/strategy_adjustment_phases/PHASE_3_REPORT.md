# Phase 3 验收报告：安全校验、隔离回测与实施预览

## 修改文件

- `agent/tools/strategy_workflow_tools.py`
- `database/repositories/strategy_workflow_repository.py`
- `tests/unit/test_strategy_backtest_does_not_change_account.py`

## 新增文件

- `agent/services/strategy_backtest_service.py`
- `agent/services/strategy_review_service.py`
- Phase 3 要求的 10 个 `test_strategy_validation_*`、`test_strategy_backtest_*`、`test_strategy_preview_*` 和语义回退测试文件

## 业务链路变化

`strategy.prepare_implementation` 现在自动完成：

```text
锁定 Proposal
→ 生成隔离 artifact
→ Canonical Config schema/关系校验
→ 生成代码静态安全扫描
→ PortfolioStrategy 统一接口加载校验
→ 隔离基线/候选同输入回测
→ 生成 StrategyImplementationPreview
→ 刷新 artifact hash 与报告 hash
```

校验内容包括：

- `max_positions <= entry_top_k <= hold_buffer_rank`
- `target_invested_weight + minimum_cash_ratio <= 1`
- 所有 canonical 数值范围
- 生成代码无真实券商、网络、系统命令、越权文件写入、Token/密钥或 WriteGateway 绕过
- 代码路径实现 `PortfolioStrategy` 接口
- 配置/组合路径不要求生成 Python

隔离回测对基线和候选使用相同日期序列、排名政策、初始资产与费率，并输出：

- 年化收益
- 最大回撤
- 波动率
- 换手率
- 现金比例
- 集中度
- 可执行率

回测服务为纯计算，明确标记不写正式账户和正式 outputs。

`StrategyImplementationPreview` 包含 Proposal 版本、实现类型、正式文件计划、配置差异、代码 diff、安全、测试、回测、风险收益权衡、回滚方案和“是否影响当前持仓”。预览 JSON 的 hash 写入 artifact manifest。

## 失败与语义保护

如果 schema/接口/安全检查失败：

- implementation 状态为 `validation_failed`
- backtest 状态为 `blocked`
- 报告完整保留
- Proposal 返回 `revising`
- 不自动修改配置或代码含义
- 不创建正式应用确认计划

## 专项测试

Phase 3：

```text
10 passed
```

Phase 2 + Phase 3 累计：

```text
20 passed
```

覆盖 schema、安全、接口、隔离、同输入、账户不变、diff、权衡、hash 绑定和语义回退。

## 回归测试

编译：

```text
passed
```

全量：

```text
888 passed, 9 failed, 255 warnings
```

9 项失败与 Phase 0 基线 9 项完全一致，没有新增失败。

## 兼容性结论

- 正式项目核心文件 hash 在隔离评审前后相同。
- 正式账户金额、持仓股数、价格、市值、盈亏不变。
- 正式 outputs 未被回测污染。
- 默认策略、历史回放和现有确认链未改变。
- 预览与 security/test/backtest 报告通过 manifest hash 绑定到同一 artifact。

## 剩余风险

- 当前隔离回测使用项目内确定性评审数据，以保证同输入、可复现和无外部副作用；正式发布前仍应在实际可用历史 ranking 数据上补充更长周期评估。
- 代码生成路径若需修改业务语义，只能回到 Proposal 讨论。
- 尚未允许正式文件或 Registry 写入；下一阶段必须经过独立 apply confirmation。

## 下一阶段入口

Phase 4 将从 `validated` implementation 创建包含 Proposal/version/artifact/report/baseline 全部 hash 的 `apply_strategy_implementation` 确认计划，并通过统一 WriteGateway revalidate/commit。成功后只能注册为 `registered_disabled`。

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
