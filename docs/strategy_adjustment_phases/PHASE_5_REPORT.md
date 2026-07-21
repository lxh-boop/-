# Phase 5 验收报告：账户级策略 Binding 与启用确认

## 修改文件

- `agent/services/strategy_apply_service.py`
- `agent/services/write_operation_service.py`
- `agent/tool_engine.py`
- `agent/tools/strategy_workflow_tools.py`
- `agent/tools/tool_registry.py`
- `agent/tools/write_operation_adapters.py`
- `agent/write_gateway.py`
- `database/table_registry.py`

## 新增文件

- `agent/services/strategy_binding_service.py`
- `database/migrations/021_strategy_bindings.sql`
- `strategies/binding_repository.py`
- `strategies/runtime_resolver.py`
- `tests/unit/strategy_binding_test_utils.py`
- Phase 5 要求的 11 个 Binding schema/activation/effective-date/history/rollback/isolation 测试文件

## 业务链路变化

策略目录与账户运行选择已经分离：

```text
Registry = 已注册策略版本目录
Binding = 用户/账户从何时起使用哪个版本
```

注册成功后自动生成下一日生效的 Activation 确认预览，但不写 Binding。第二次确认链：

```text
Activation Preview
→ activate_strategy_binding plan
→ 用户确认
→ WriteGateway
→ strategy.binding.commit
→ revalidate 当前 Binding + manifest + config hash
→ 写入用户/账户级 Binding
```

该流程不调用全局 `registry.enable()`，不修改 `enabled_for_paper_trading`，不修改当前持仓或订单。

## Binding 状态与生效日

- 当日生效：新 Binding 为 `active`，旧 active 标记 `replaced`。
- 未来生效：新 Binding 为 `scheduled`，当前 active 保持；Resolver 到生效日选择 scheduled 版本。
- 新的 scheduled 会把同账户旧 scheduled 标为 `superseded`。
- 历史行不删除。
- 每个用户/账户最多一条数据库 `active` 行。

回滚不是删除或恢复旧行，而是：

```text
读取 current.previous_binding_id
→ 创建 rollback_strategy_binding 确认计划
→ 用户确认
→ 新增一条指向旧策略版本的 Binding
```

## Runtime Resolver

`StrategyRuntimeResolver` 返回 canonical 配置：

- strategy_id / strategy_version
- binding_id / config_hash
- entry_top_k
- hold_buffer_rank
- max_positions
- target_invested_weight
- minimum_cash_ratio
- min_rebalance_weight_delta

无 Binding 时回退内置默认策略，参数与 Phase 0 基线一致。

## 数据库迁移

`021_strategy_bindings.sql` 新增 `strategy_bindings`，包含用户/账户作用域、策略版本、config hash、生效日、状态、前一 Binding、来源 Plan 和激活/停用时间；partial unique index 约束每账户单一 active。

## 专项测试

```text
11 passed
```

覆盖：

- schema 与唯一索引
- 激活必须确认
- 用户/账户作用域
- 启用不改账户/持仓
- 生效日期
- 单一 active
- 旧版本保留
- 回滚再确认
- 无 Binding 默认回退
- 跨用户、跨账户隔离

## 回归测试

应用确认和默认策略关键回归：

```text
8 passed
```

全量：

```text
910 passed, 9 failed, 255 warnings
```

9 项失败与 Phase 0 基线一致，没有新增失败。

## 兼容性结论

- 无 Binding 用户保持原默认参数。
- 用户 A 的 Binding 不影响用户 B。
- 同一用户不同账户互不影响。
- Registry list/register 保持兼容。
- 原策略版本和 Binding 历史均可查询。
- 策略注册、账户启用和当前持仓修改仍是三次独立操作。

## 剩余风险

- Resolver 已实现但每日模拟盘和历史回放尚未消费它；Phase 6 将接入实际 Pipeline。
- 未来 scheduled Binding 当前由 Resolver 按日期选择，数据库状态本身不需要定时转换为 active。
- 全局 Registry enable 字段为旧兼容字段，不再作为账户运行选择依据。

## 下一阶段入口

Phase 6 将让每日模拟盘和 backfill 使用同一 Resolver，并让分层 Top10 路径真实消费全部 canonical 参数，同时把策略元数据写入调仓计划、订单和账户历史。

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
