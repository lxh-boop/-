# Phase 1 验收报告：策略方案对话与版本化草案

## 修改文件

- `agent/executor.py`
- `agent/intent_decomposition/layered_decomposer.py`
- `agent/intent_decomposition/prompts.py`
- `agent/intent_decomposition/rule_fallback.py`
- `agent/intent_decomposition/schemas.py`
- `agent/tool_engine.py`
- `agent/tools/tool_registry.py`
- `agent/tools/write_operation_adapters.py`
- `database/repositories/__init__.py`
- `database/table_registry.py`

## 新增文件

- `agent/services/strategy_context_service.py`
- `agent/services/strategy_proposal_service.py`
- `agent/tools/strategy_workflow_tools.py`
- `database/migrations/019_strategy_conversation_workflow.sql`
- `database/repositories/strategy_workflow_repository.py`
- `tests/unit/strategy_workflow_test_utils.py`
- `tests/unit/test_strategy_context_loading.py`
- `tests/unit/test_strategy_proposal_create.py`
- `tests/unit/test_strategy_proposal_revision.py`
- `tests/unit/test_strategy_proposal_version_history.py`
- `tests/unit/test_strategy_short_feedback_keeps_context.py`
- `tests/unit/test_strategy_acknowledgement_asks_before_implementation.py`
- `tests/unit/test_strategy_explicit_implementation_does_not_reask.py`
- `tests/unit/test_strategy_negation_does_not_implement.py`
- `tests/unit/test_strategy_llm_failure_keeps_draft.py`
- `tests/unit/test_strategy_cross_conversation_isolation.py`
- `tests/unit/test_strategy_cross_user_isolation.py`

## 业务链路变化

长期策略对话主链路调整为：

```text
用户消息
→ 加载用户/账户/会话级 StrategyConversationContext
→ LLM 结合当前账户、持仓、真实策略参数、能力、约束、相关对话和 Proposal 历史决定 conversation_action
→ strategy.save_proposal_draft 原样保存 LLM 产生的 proposal_json
→ 同一 Proposal 追加不可覆盖的版本
```

`conversation_action` 只接受：

```text
continue_discussion
save_proposal
ask_implementation
prepare_implementation
llm_unavailable
```

确定性工具不解释“稳健、激进、少换手”等业务含义，不根据关键词决定是否实施。仅认可且上下文不能确认实施意图时固定回复“那现在需要我开始调整策略吗？”。明确实施只产生 `implementation_requested=true`，本阶段不会生成代码、确认计划或正式写入。

LLM 不可用时只保存原始请求占位草案，并询问是否开始调整；不会自动实施。有活动 Proposal 时，短反馈继续按相同用户、账户和会话路由。

新增的高层工具：

- `strategy.get_context`
- `strategy.get_active_proposal`
- `strategy.save_proposal_draft`

草案保存不是正式业务变更，不经 WriteGateway，也不创建 confirmation plan。Registry、Binding、当前持仓、订单和资金均不变。

## 数据库迁移

项目原有迁移已使用编号 018，因此使用 `019_strategy_conversation_workflow.sql`，新增：

- `strategy_proposals`
- `strategy_proposal_versions`

Proposal 按 `user_id + account_id + conversation_id` 隔离，版本以 `proposal_id + version` 为联合主键并只追加。

## 专项测试

命令使用：

```powershell
D:\stock_daily_app\.venv\Scripts\python.exe -m pytest <Phase 1 的 11 个 test_strategy_*.py> -q
```

结果：

```text
11 passed
```

修复兼容问题后复测相关专项和兼容用例：

```text
13 passed
```

## 回归测试

关键策略、模拟盘、Agent、会话、RAG 与 WriteGateway 兼容集执行后，仅出现 Phase 0 已记录的“一手不足提示文案”既有失败；未新增兼容失败。

全量命令：

```powershell
D:\stock_daily_app\.venv\Scripts\python.exe -m pytest tests\unit -q
```

最终结果：

```text
869 passed, 8 failed, 255 warnings
```

8 项失败均包含在 Phase 0 的 9 项既有失败集合内，没有新增失败；其中原基线的 `test_observe_marks_tool_success_but_goal_incomplete_as_partial` 已恢复通过。

## 兼容性结论

- 默认策略运行和 Phase 0 golden 未改变。
- 原 `strategy_builder_tool` 仍保留为兼容接口，但 Agent 长期策略对话主链不再调用它创建注册确认计划。
- one-time position、资金、回放和统一确认链未改变。
- ranking、股票分析、news/RAG、会话切换等只读入口未被策略草案写入逻辑替代。
- 草案跨用户、跨账户和跨会话隔离。

## 剩余风险

- LLM 输出的策略含义质量依赖模型；工具只验证结构并原样持久化。
- 当前 Proposal 仅完成讨论与版本化，尚未有隔离实现 artifact。
- 现有 Registry 仍是全局 JSON 权威，且当前模拟盘 Pipeline 尚未消费 Registry；后续阶段将通过账户级 Binding 与 Runtime Resolver 解决。

## 下一阶段入口

Phase 2 将锁定 Proposal 版本，创建 `strategy.prepare_implementation`，并只在：

```text
runtime/strategy_drafts/<user_id>/<proposal_id>/v<version>/
```

生成隔离配置或插件草案，不修改正式项目、Registry、账户或持仓。

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
