# Phase 2 验收报告：隔离实施准备

## 修改文件

- `agent/executor.py`
- `agent/tool_engine.py`
- `agent/tools/strategy_workflow_tools.py`
- `agent/tools/tool_registry.py`
- `agent/tools/write_operation_adapters.py`
- `database/repositories/strategy_workflow_repository.py`
- `database/table_registry.py`
- `tests/unit/strategy_workflow_test_utils.py`

## 新增文件

- `agent/services/strategy_config_compiler.py`
- `agent/services/strategy_code_generation_service.py`
- `agent/services/strategy_implementation_service.py`
- `agent/services/strategy_validation_service.py`
- `database/migrations/020_strategy_implementations.sql`
- Phase 2 要求的 10 个 `test_*implementation*.py` / 隔离与安全专项测试文件

## 业务链路变化

明确实施请求的主链路为：

```text
LLM 基于完整上下文选择 prepare_implementation
→ 保存/复用精确 Proposal 版本
→ strategy.prepare_implementation
→ 校验用户、账户、会话和版本
→ 锁定 Proposal
→ 结构化编译 ImplementationSpec
→ 只在 runtime/strategy_drafts/<user>/<proposal>/v<version>/ 生成 artifact
```

高层工具只接收：

```text
proposal_id
proposal_version
user_id
account_id
conversation_id
run_id
```

不接收“稳健一点”等自由文本，不重新解释 Proposal。

实现路径：

- `config`：只生成 `generated_config.json`，不生成 Python。
- `composite`：只在隔离目录生成组合描述。
- `code`：只在隔离目录生成实现统一 Strategy 接口的插件草稿。

所有路径都会生成：

- `proposal_snapshot.json`
- `implementation_spec.json`
- `generated_config.json`
- `generated_code/`
- `diff.patch`
- `security_report.json`
- `test_report.json`
- `backtest_report.json`
- `implementation_preview.md`
- `artifact_manifest.json`

artifact manifest 记录每个文件 SHA-256、整体 implementation hash、Proposal 版本和计划中的正式文件。重复调用同一 Proposal 版本返回同一个 implementation，不生成冲突草稿。

## 数据库迁移

`020_strategy_implementations.sql` 新增 `strategy_implementations`，保存：

- implementation/proposal/version 标识
- 用户、账户、会话作用域
- 实现类型和隔离 artifact 路径
- implementation hash 与 manifest hash
- 状态和时间

`proposal_id + proposal_version` 唯一。

## 专项测试

结果：

```text
10 passed
```

覆盖：

- 未锁定 Proposal 不能直接准备。
- 过期 Proposal 版本拒绝。
- 配置路径不生成代码。
- 组合和代码路径严格隔离。
- 生成器不能写正式项目。
- 生成代码不导入真实券商或网络/命令模块。
- 生成代码不能调用 WriteGateway 或确认令牌。
- artifact hash 覆盖全部清单文件。
- 重复调用幂等。
- 跨用户读取/准备拒绝。

## 回归测试

关键兼容集：

```text
24 passed, 1 个 Phase 0 既有失败
```

全量：

```text
879 passed, 8 failed, 255 warnings
```

8 项失败全部属于 Phase 0 已记录的既有失败集合，没有新增失败。

## 兼容性结论

- 原 `hierarchical_top10_allocator.py` hash 未变。
- 正式 `strategies/`、`portfolio/`、`agent/` 和数据库业务状态不会被生成器写入。
- 正式 Registry、账户、持仓、订单和净值不变。
- 原策略 Builder 兼容接口、模拟盘默认策略与确认链仍可用。
- 隔离目录由用户和 Proposal 作用域组成，跨用户访问被服务层拒绝。

## 剩余风险

- 本阶段仅做生成时静态边界扫描；完整 schema、统一接口、隔离回测、基线对比和可执行率验证在 Phase 3 完成。
- 代码路径生成的是隔离插件骨架；如果用户策略语义不能由当前结构化 ImplementationSpec 表达，会返回 Proposal 讨论，不由工具自行改义。
- 正式应用尚不存在；所有 artifact 仍为隔离草稿。

## 下一阶段入口

Phase 3 将对同一 implementation hash 完成 schema、接口和安全验证，使用临时账户/输出运行基线与候选策略回测，并生成绑定 hash 的 `StrategyImplementationPreview`。

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
