# Phase 6 验收报告：模拟盘真实消费策略版本

## 修改范围

- `pipelines/paper_trading_pipeline.py`
- `pipelines/schemas.py`
- `portfolio/rebalance_rules.py`
- `portfolio/paper_strategy_config.py`
- `portfolio/trading_cost_config.py`
- `portfolio/hierarchical_top10_allocator.py` 的调用参数链
- `portfolio/paper_trading_engine.py`
- `portfolio/paper_order.py`
- `portfolio/schemas.py`
- `portfolio/storage.py`
- `strategies/runtime_resolver.py`
- `strategies/adapters/hierarchical_top10_strategy.py`
- `database/repositories/portfolio_repository.py`
- `database/table_registry.py`

## 新增迁移

- `database/migrations/022_strategy_runtime_audit.sql`
- `database/migrations/023_paper_decision_strategy_metadata.sql`

新增了订单、决策、账户快照的策略版本字段，以及
`paper_strategy_execution_history` 全链路执行历史表。

## 运行链路

```text
Strategy Binding
→ StrategyRuntimeResolver
→ paper_trading_pipeline
→ rebalance_rules
→ hierarchical_top10_allocator / generated plugin
→ TargetPortfolio
→ paper trading engine
```

日常模拟盘和 backfill 都通过 `run_paper_trading_pipeline` 使用相同
Resolver。Binding 存在时，旧入口参数不能覆盖 Binding；无 Binding
时返回 Phase 0 的内置默认策略。

## Canonical Runtime Config

运行时内部统一使用：

- `entry_top_k`
- `hold_buffer_rank`
- `max_positions`
- `target_invested_weight`
- `minimum_cash_ratio`
- `min_rebalance_weight_delta`

兼容边界仍接受：

- `top_n` → `entry_top_k` 与 `max_positions`
- `target_ratio` → `target_invested_weight`
- `min_cash_ratio` → `minimum_cash_ratio`

分层路径不再无条件使用固定 `TOP10_TARGET_RATIO`。目标投资比例会先受
最小现金比例约束，再考虑交易权限冻结仓位；`max_positions`、缓冲排名和
最小调仓阈值均进入实际目标组合与订单判断。

## 插件消费

Resolver 会按 Registry 中的 `module_path` 与 `class_name` 加载经注册的
`PortfolioStrategy`。非内置插件通过 `StrategyContext` 生成
`StrategyResult`，其目标权重进入同一调仓、权限、费用和模拟盘执行链。

## 策略元数据

每次调仓计划、订单、决策、账户快照和策略执行历史均记录：

- `strategy_id`
- `strategy_version`
- `binding_id`
- `config_hash`
- `resolved_config`

策略执行历史还保留：

- 调仓前持仓
- TargetPortfolio
- 订单
- 调仓后持仓
- 调仓前后现金

## 专项测试

Phase 6 指定的 11 项测试：

```text
11 passed
```

覆盖 Binding/default Resolver、Pipeline 实际消费、六项运行参数、插件
目标生成、元数据、backfill 配置一致性和默认 golden。

## 关键回归

交易权限、一手约束、最短持有、Top15 Buffer、费用、缺失价格、历史订单
和回填等关键测试：

```text
19 passed
```

默认策略 golden：

```text
TargetPortfolio 一致
订单列表一致
现金、持仓和费用一致
```

## 全量回归

```text
921 passed, 9 failed, 255 warnings
```

9 项失败与 Phase 0 基线完全一致，没有新增失败。改造中曾发现决策表缺少
策略元数据列，已通过 `023_paper_decision_strategy_metadata.sql` 修复并
完成全量复跑。

## 下一阶段入口

Phase 7 将在已落地的 `paper_strategy_execution_history` 基础上实现
“预览当前持仓变化 → 独立确认 → revalidate → 原模拟盘执行链”，并验证
策略切换、回滚、持仓、订单、净值和资金历史都不会被删除。

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
