# Phase 12-D Executor / ToolExecutor / UserGoal / TaskPlan Integration Report

## 阶段目标

将 Phase 12 `ContextManager` 以兼容方式接入 Agent 主执行链：Executor 创建 `ContextBundle`，ToolExecutor 可接收 `context_bundle` / `tool_context`，工具结果可回写 ContextBundle，UserGoal / TaskPlan 可读取 context refs。旧 dict context 调用保持兼容。

## 修改前状态

| 模块 | 修改前 | 本阶段处理 |
| --- | --- | --- |
| `agent/executor.py` | 只生成旧 `BuiltAgentContext` 压缩文本 | 新增 Phase 12 `ContextBundle` 创建、safe route context、工具结果回写和 snapshot |
| `agent/tool_engine.py` | `ToolExecutor.execute(..., context=dict)` | 新增可选 `context_bundle` / `tool_context` 参数；旧调用自动 minimal context |
| `agent/goal_planning.py` | UserGoal/TaskPlan 只读旧 context dict | 读取 `context_bundle` minimal refs，写入 `system_generated_parameters` 和 `required_artifacts` |

## 修改文件

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `agent/tool_engine.py` | 修改 | ToolExecutor 支持 `context_bundle` / `tool_context`，工具成功后回写 ContextBundle |
| `agent/executor.py` | 修改 | 创建 `ContextManager` / `ContextBundle`，向 route context 注入 safe/minimal context，保存 snapshot |
| `agent/goal_planning.py` | 修改 | UserGoal/TaskPlan 读取 context_id、artifact refs、pending plan refs |
| `tests/unit/test_phase12_context_tool_executor.py` | 新增 | ToolExecutor bundle/minimal 兼容测试 |
| `tests/unit/test_phase12_context_executor_integration.py` | 新增 | Executor 与 planning 集成测试 |

## Executor 接入点

新增逻辑：

- `ContextManager(db_path, output_dir)`
- `create_initial_context(user_id, query, conversation_id, run_id, locale)`
- 将 `context_bundle.to_minimal_context()` 和 `build_llm_context()` 放入 `route_context`
- `_registered_tool()` 调用 v2 ToolExecutor 时传入 `context_bundle` 和 `tool_context`
- 工具结果后调用 `update_from_tool_result()`
- 返回结果 `context.phase12_context` 包含：
  - `context_id`
  - `llm_context`
  - `minimal_context`
- 保存 `<output_dir>/context_snapshots/<user_id>/<context_id>.json`

旧的 `pre_execution` / `post_observation` `BuiltAgentContext` 仍保留。

## ToolExecutor 接入点

新增签名：

```text
execute(tool_name, arguments, context=None, context_bundle=None, tool_context=None, ...)
```

兼容行为：

- 未传 `context_bundle`：`context_mode = minimal`
- 传入 `context_bundle`：按 `ContextSanitizer.sanitize_for_tool()` 合并安全 tool view
- 写权限规则、agent_type allowlist、approval_required 行为未变
- 工具成功后回写 `ToolContext.result_summary` 和 `ArtifactContext.artifact_refs`

## UserGoal / TaskPlan 接入点

新增读取：

- `context_bundle.context_id`
- `context_bundle.user_id`
- `context_bundle.conversation_id`
- `artifact_refs`
- `approval.pending_plan_id`

写入：

- `UserGoal.system_generated_parameters.context_id`
- `UserGoal.inherited_parameters.available_context_refs`
- `TaskPlan.required_artifacts`
- `TaskPlan.completion_contract.available_context_refs`

业务分类和任务选择逻辑未改。

## 兼容旧接口说明

- `execute_tool_legacy_dict()` 不需要传 `context_bundle`，仍正常返回 legacy dict。
- `ToolExecutor.execute()` 旧调用仍可用，测试显示 `context_mode=minimal`。
- `run_agent_request()` 返回的旧 `context.pre_execution`、`context.post_observation` 保持存在。
- P0 Write Gateway 和 P1-A portfolio proposal / paper trade commit 回归通过。

## 测试命令与结果

| 命令 | 结果 |
| --- | --- |
| `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts` | pass |
| `py -3 -m pytest tests/unit/test_phase12_context_executor_integration.py -q` | 2 passed |
| `py -3 -m pytest tests/unit/test_phase12_context_tool_executor.py -q` | 2 passed |
| `py -3 -m pytest tests/unit/test_phase12_context_store_resolver.py -q` | 2 passed |
| `py -3 -m pytest tests/unit/test_phase12_context_core.py -q` | 2 passed |
| `py -3 -m pytest tests/unit/test_phase12_context_policy.py -q` | 4 passed |
| `py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q` | 7 passed |
| `py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q` | 6 passed |
| `py -3 -m pytest tests/unit/test_agent_write_requires_confirmation.py -q` | 1 passed |
| `py -3 -m pytest tests/unit/test_agent_action_proposal_gateway.py -q` | 3 passed |
| `py -3 -m pytest tests/unit/test_multi_agent_phase3_human_approval.py -q` | 5 passed |
| `py -3 -m pytest tests/unit/test_phase10_goal_planning.py -q` | 13 passed |
| `py -3 -m pytest tests/unit/test_phase10_3_capability_artifacts.py -q` | 9 passed |
| `py -3 -m pytest tests/unit/test_phase11_p1a_portfolio_proposal_tools.py -q` | 6 passed |

Known warnings: existing `datetime.utcnow()` deprecation warnings in `agent/capability_index.py`.

## 真实网页功能检查记录

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = playwright

WEB_CHECK_PAGES = [`http://127.0.0.1:8501/_stcore/health`, `首页 / 预测排名`, `AI Agent`, `AI 模拟盘`, `系统监控`]

WEB_CHECK_RESULT = pass

WEB_CHECK_ERRORS = []

### AI Agent 输入测试

| input | expected | actual_summary | result |
| --- | --- | --- | --- |
| `查看我的当前持仓` | 返回持仓或安全提示，不报错 | 返回当前模拟盘状态，包含持仓数量、总资产、现金、持仓市值和持仓明细 | pass |
| `分析当前组合风险` | 返回风险分析或安全提示，不报错 | 返回风险等级、最大单股仓位、现金比例、单股/行业集中度风险提示，并明确不执行写入 | pass |
| `给我一个调仓建议` | 能生成 proposal 或说明缺少信息，不直接执行 | 返回调仓建议与候选证据，明确“只生成只读分析，不执行写入、审批或 Commit” | pass |

### 页面检查摘要

| 页面 | 关键功能 | 结果 |
| --- | --- | --- |
| health | `_stcore/health` -> `ok` | pass |
| 首页 / 预测排名 | 标题、模型库管理、手动生成预测排名、每日更新并生成预测排名 | pass |
| AI Agent | 真实输入测试通过；未发现 `confirmation_token` 明文 | pass |
| AI 模拟盘 | 更新入口、用户与账户摘要、持仓、风险 | pass |
| 系统监控 | 总状态、保存监控快照、Runtime Reliability | pass |

未发现：Traceback、ModuleNotFoundError、NameError、KeyError、Unhandled exception、页面乱码、`confirmation_token` 明文。

## 失败项

无。

## 未完成项

- UI 尚未展示 context 安全摘要或 context id。
- 尚未做最终覆盖率和交付报告。

这些内容按阶段 E-F 执行。

NEXT_STAGE_ALLOWED = true
