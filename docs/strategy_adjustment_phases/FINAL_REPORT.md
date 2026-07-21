# 模拟盘长期策略调整最终交付报告

## 最终结论

长期策略调整已形成以下安全闭环：

```text
LLM 基于完整会话理解需求
-> 多轮版本化 Proposal
-> 用户明确要求实施
-> 锁定 Proposal 版本
-> runtime/strategy_drafts 隔离实现
-> schema / security / interface / test / backtest
-> 第一次确认：应用并注册
-> registered_disabled
-> 第二次确认：启用未来策略
-> user + account + effective_date Binding
-> 原 paper_trading_pipeline 消费 ResolvedStrategyConfig
-> 第三次确认：执行当前模拟盘调仓
-> 保留策略版本、订单和持仓前后审计
```

无 Binding 用户继续使用默认 `hierarchical_top10`；个性化策略不会覆盖原代码，
不会跨用户或账户生效，不会因为注册或启用而立即改变当前持仓。

## 1. 修改文件清单

核心修改文件：

- 文档：`AGENTS.md`、`PROJECT_STRUCTURE.md`、`PROJECT_FILE_DIRECTORY.md`
- Agent 主链：`agent/executor.py`、`agent/intent_decomposition/*`、
  `agent/tool_engine.py`、`agent/tools/tool_registry.py`、
  `agent/tools/write_operation_adapters.py`
- 写边界：`agent/services/write_operation_service.py`、
  `agent/session/confirmation_manager.py`、`agent/write_gateway.py`
- UI：`app/pages/ai_agent.py`
- Pipeline：`pipelines/paper_trading_pipeline.py`、`pipelines/schemas.py`
- Portfolio：`portfolio/paper_order.py`、`paper_strategy_config.py`、
  `paper_position.py`、`paper_trading_engine.py`、`rebalance_rules.py`、
  `schemas.py`、`storage.py`、`trading_cost_config.py`
- Strategy：`strategies/registry.py`、
  `strategies/adapters/hierarchical_top10_strategy.py`
- Database：`database/table_registry.py`、
  `database/repositories/portfolio_repository.py`、
  `database/repositories/__init__.py`

## 2. 新增文件清单

生产代码：

- `agent/services/strategy_proposal_service.py`
- `agent/services/strategy_context_service.py`
- `agent/services/strategy_config_compiler.py`
- `agent/services/strategy_code_generation_service.py`
- `agent/services/strategy_implementation_service.py`
- `agent/services/strategy_validation_service.py`
- `agent/services/strategy_backtest_service.py`
- `agent/services/strategy_review_service.py`
- `agent/services/strategy_apply_service.py`
- `agent/services/strategy_binding_service.py`
- `agent/services/strategy_position_service.py`
- `agent/services/strategy_audit_service.py`
- `agent/tools/strategy_workflow_tools.py`
- `database/repositories/strategy_workflow_repository.py`
- `strategies/binding_repository.py`
- `strategies/runtime_resolver.py`

数据库和报告：

- `database/migrations/019_strategy_conversation_workflow.sql`
- `database/migrations/020_strategy_implementations.sql`
- `database/migrations/021_strategy_bindings.sql`
- `database/migrations/022_strategy_runtime_audit.sql`
- `database/migrations/023_paper_decision_strategy_metadata.sql`
- `docs/strategy_adjustment_phases/PHASE_0_REPORT.md` 至
  `PHASE_8_REPORT.md`
- `docs/strategy_adjustment_phases/FINAL_REPORT.md`

测试：

- `tests/fixtures/strategy_default_golden.json`
- `tests/unit/strategy_*_test_utils.py`
- Phase 0—8 新增的 strategy/apply/binding/runtime/position 专项测试文件；
  每个阶段的完整文件名见对应 Phase 报告。

## 3. Database migration

| Migration | 内容 |
|---|---|
| 019 | `strategy_proposals` 与不可变 Proposal 版本历史 |
| 020 | 锁定 Proposal 版本对应的隔离 `strategy_implementations` |
| 021 | 用户/账户/生效日隔离的 `strategy_bindings` 及历史 |
| 022 | 订单、设置、账户快照策略元数据与 `paper_strategy_execution_history` |
| 023 | `paper_decision_log` 的策略版本、Binding、config hash 和 resolved config |

安装版仍只运行 migration 初始化用户数据库，不复制开发机 live 数据。

## 4. 工具与 Skill

新增/接入的主要工具：

```text
strategy.get_context
strategy.get_active_proposal
strategy.save_proposal_draft
strategy.prepare_implementation
strategy.create_apply_plan
strategy.apply.commit
strategy.create_activation_plan
strategy.create_binding_rollback_plan
strategy.binding.commit
strategy.preview_current_position_change
strategy.position.commit
strategy.get_audit_trace
```

只读、proposal、preview 和 write 权限分别注册。所有正式 write 都经过
WriteGateway、独立确认、revalidate、幂等 commit 和审计。

本功能不新增会在项目外执行的 Codex Skill；Web 验收使用已安装的浏览器控制
Skill。策略业务能力作为项目内 Tool/Service 实现，避免让工具自行定义策略含义。

## 5. 完整状态机

```text
discussion
  -> draft/revising
  -> locked_for_implementation
  -> implementation_ready
  -> generated
  -> validated | validation_failed
  -> apply_plan_pending
  -> registered_disabled
  -> activation_plan_pending
  -> binding_scheduled | binding_active
  -> position_plan_pending
  -> paper_position_committed

任一确认：
  pending -> confirmed -> executed
          -> rejected | expired | revalidation_failed

Binding：
  scheduled/active -> replaced/superseded
  rollback -> 新 Binding，旧历史不删除
```

## 6. 完整调用链

```text
app/pages/ai_agent.py
-> agent/executor.py
-> intent decomposition + full conversation context
-> strategy workflow tools
-> Proposal/Implementation services
-> runtime/strategy_drafts
-> validation/review/backtest
-> confirmation_manager + WriteGateway
-> StrategyApplyService + StrategyRegistry
-> StrategyBindingService + StrategyBindingRepository
-> StrategyRuntimeResolver
-> pipelines/paper_trading_pipeline.py
-> portfolio/rebalance_rules.py
-> portfolio/paper_trading_engine.py
-> PortfolioStorage / repository / execution history
```

## 7. Phase 报告

- `PHASE_0_REPORT.md`：边界、基线、默认 golden。
- `PHASE_1_REPORT.md`：Proposal、对话和版本历史。
- `PHASE_2_REPORT.md`：隔离实现、安全、测试和回测。
- `PHASE_3_REPORT.md`：真实参数语义和插件接口验证。
- `PHASE_4_REPORT.md`：应用确认、原子注册、幂等和回滚。
- `PHASE_5_REPORT.md`：账户 Binding、启用和回滚确认。
- `PHASE_6_REPORT.md`：模拟盘 Pipeline 真实消费运行时策略。
- `PHASE_7_REPORT.md`：当前持仓第三次确认与历史保留。
- `PHASE_8_REPORT.md`：UI、审计、降级、文档和最终验收。

## 8. 最终测试报告

- 编译：通过。
- 默认策略 golden：TargetPortfolio、订单、费用、现金和持仓保持一致。
- `test_strategy_*.py`：`35 passed`。
- 关键回归：`70 passed, 4 failed`；失败属于 Phase 0 既有集合。
- 全量：`939 passed, 8 failed, 255 warnings`；8 项均为 Phase 0 既有失败，
  没有新增失败。
- Web：`http://127.0.0.1:8501` 健康检查为 `ok`；真实浏览器检查首页/
  预测排名、AI Agent、AI 模拟盘当前持仓和历史视图、系统监控均正常，
  无 Streamlit exception、无 console error、无 confirmation token 泄露。
- 运行解释器：`D:\stock_daily_app\.venv\Scripts\python.exe`，基础解释器为
  `D:\python_runtime\cpython-3.12.0-windows-x86_64-none\python.exe`。

## 9. 原功能兼容性

- 默认策略 golden 完全一致。
- 无 Binding 用户不改变。
- 原持仓、订单、净值、资金流水和回放历史仍可查询。
- 一次性持仓操作、资金变更、backfill 和原确认链保持独立。
- MCP 和 Specialist 仍不能直接写业务状态。
- 原策略代码不会被个性化请求覆盖。
- 用户、账户和会话隔离均有专项测试。
- 注册、启用和当前仓位修改是三次独立操作。
- 新 Binding 参数真实改变 TargetPortfolio 和订单，并被 backfill 共用。

## 10. 真实限制

- LLM 对策略语义的理解依赖可用的外部 LLM 配置；不可用时只保留请求/草稿，
  不会自动实施。
- Strategy Registry 文件仍是运行时注册清单，SQLite 是审计镜像；应用服务通过
  文件快照和数据库清理实现失败回滚，但不是跨文件系统和 SQLite 的单一 ACID
  事务。
- 旧历史记录若在 019—023 migration 之前产生，缺失的 Proposal/Binding/config
  元数据无法凭空补全。
- 代码型策略只允许受控 `PortfolioStrategy` 接口和隔离产物，禁止任意券商、
  subprocess、网络和正式项目写入。
- 本项目只有模拟盘，不接入真实券商，不用于实盘交易。

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
