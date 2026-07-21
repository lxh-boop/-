# Phase 4 验收报告：正式应用确认与禁用版本注册

## 修改文件

- `agent/executor.py`
- `agent/services/write_operation_service.py`
- `agent/session/confirmation_manager.py`
- `agent/tool_engine.py`
- `agent/tools/__init__.py`
- `agent/tools/strategy_workflow_tools.py`
- `agent/tools/tool_registry.py`
- `agent/tools/write_operation_adapters.py`
- `agent/write_gateway.py`
- `strategies/registry.py`
- `tests/unit/strategy_workflow_test_utils.py`

## 新增文件

- `agent/services/strategy_apply_service.py`
- `tests/unit/strategy_apply_test_utils.py`
- Phase 4 要求的 11 个 apply/revalidate/rollback/idempotency/audit 专项测试文件

## 业务链路变化

完整正式应用链：

```text
validated StrategyImplementationPreview
→ strategy.create_apply_plan
→ pending apply_strategy_implementation plan
→ 用户确认
→ execute_confirmed_plan_v2
→ WriteGateway
→ strategy.apply.commit
→ confirmation + full revalidate
→ 事务性新增正式配置/插件
→ Registry 注册 registered_disabled
```

Plan 包含并由 plan hash 保护：

- Proposal ID / version
- implementation ID / hash
- artifact manifest hash
- diff/security/test/backtest report hash
- 正式代码基线 hash
- 策略配置 hash
- 用户、账户、会话、run ID
- 到期时间

提交前会重新计算每个 artifact 文件 hash，不只信任 manifest；同时检查 Proposal 版本/状态、implementation 状态、正式代码基线和 Registry 重复版本。

## 正式写入规则

- 配置路径新增 `strategies/config_versions/...json`。
- 代码路径新增 `strategies/generated/.../strategy_plugin.py`。
- 组合路径新增独立 composition 文件。
- 不覆盖原策略文件。
- Registry manifest 状态为 `registered_disabled`。
- `enabled_for_paper_trading=false`。
- 不创建账户 Binding，不修改持仓。

如果文件复制、Registry 注册或状态持久化任一步失败：

- 删除本次新增正式目录
- 恢复 Registry 文件快照
- 清理 Registry SQLite 镜像行
- 将确认计划标为 revalidation/apply failure
- 记录 rejected commit

## 兼容性修正

`agent.tools` 的公共 `ToolSpec/get_tool_registry/list_tools` 改为惰性加载，保留原导入 API，同时避免服务层导入审计工具时整包循环初始化。

确认计划审计现在在 `run_id` 尚未落入 `agent_runs` 时将 FK 列保存为 NULL，并把原 run ID 写入 metadata，避免审计提案因可选外键缺失被静默丢弃。

## 专项测试

```text
11 passed
```

覆盖：

- 未确认不写。
- Plan hash 覆盖全部必需字段。
- 草稿和正式代码基线改变时拒绝。
- 配置注册为禁用版本。
- 新插件不覆盖原文件。
- 文件和 Registry 双向回滚。
- 同一 Plan 只提交一次。
- 跨用户确认拒绝。
- proposal/approval/commit/action 审计完整。

## 原功能回归

确认、WriteGateway、模拟盘提案、默认策略关键回归：

```text
19 passed
```

全量：

```text
900 passed, 8 failed, 255 warnings
```

8 项失败均属于 Phase 0 既有失败集合，没有新增失败。

## 兼容性结论

- 原策略版本和原代码 hash 保留。
- 非策略 WriteGateway 操作全部通过关键回归。
- capital、backfill、持仓确认链未改变。
- 正式应用、策略启用和当前持仓修改仍是彼此独立操作。
- 新版本注册后不会自动影响任何账户。

## 剩余风险

- Registry 文件仍是策略目录权威，SQLite 为镜像；账户级运行选择将在 Phase 5 通过 Binding 单独建立。
- 本阶段完成注册但没有激活任何账户。
- 正式发布打包需在 Phase 8 验证隔离草稿不进入分发产物。

## 下一阶段入口

Phase 5 将新增 `strategy_bindings`、用户/账户级唯一 active Binding 和 `StrategyRuntimeResolver`，通过第二次独立确认激活未来策略；无 Binding 时严格回退默认策略。

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
