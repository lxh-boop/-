# Portfolio / Replan / TopK 根因排查报告

排查日期：2026-07-17  
范围：模拟盘只读状态、Agent Completion / Critic 只读 Replan、Ranking `top_k` 传递。  
约束：本阶段只进行了读取、搜索、临时目录复现和无副作用测试；未修改业务代码、数据库结构或生产数据。

## 1. 执行摘要

三个问题均已定位到确定的代码路径。

1. **账户与持仓状态不一致**：`PortfolioService.get_portfolio_state()` 在 [agent/services/portfolio_service.py](../../agent/services/portfolio_service.py) 分别读取账户和持仓，却以账户文件中的历史汇总字段生成 `summary`，同时把持仓文件明细原样返回。它没有构建同一时点的归一化快照，也不校验账户、持仓的账户标识与时点。`PortfolioStorage.save_account()` 与 `save_positions()` 亦是两个独立持久化动作。因此任何陈旧账户汇总、交错写入或旧数据都能稳定产生“账户市值为零、持仓明细有市值”的输出。
2. **`REPLAN_READONLY` 未实际执行**：Completion 在主执行完成后才写入 `result_dict["llm_completion"]`，Reflection Critic 更晚才产生 `CriticAction.REPLAN_READONLY`；两者均没有消费者回到任务规划和执行器。Phase 15 的 `ReplanPolicy` 仅保存观察、生成决定并发布消息，也不记录 limiter 或执行新计划。现有 `multi_task_executor` 的 Replan 只消费工具任务失败/固定 fallback，不能消费 Completion/Critic 的动作。因此日志能出现请求动作，而 `replan_count` 和 `replan_audit` 仍是零。
3. **`top_k` 被规则 fallback 固定为 50**：`rule_fallback.py` 在没有文本“十”或 `top10` 时直接创建 `ranking(top_k=50)`，覆盖了调用层传入的 `default_top_k=10`。虽然 `ArgumentResolver` 对已有任务参数采用 `setdefault`，但此时参数已经是 50。`run_agent_request()` 还存在未调用的 `_requested_top_k()`；实际入口仅使用用户解析参数或请求默认值，形成多套未统一的优先级规则。

## 2. 持仓状态证据链

### 2.1 实际读取链路

```text
PortfolioStorage 最新账户 JSON / 最新持仓 CSV
    -> PortfolioService.get_account_summary()（直接信任账户汇总字段）
    -> PortfolioService.get_current_positions()（独立读取持仓明细）
    -> PortfolioService.get_portfolio_state()（把两者拼接）
    -> portfolio.get_state adapter / Context 压缩 / 最终回答

PortfolioService.get_portfolio_state()
    -> PortfolioRiskService.analyze_current_risk()
    -> 旧风险快照优先，或再次独立读取 account + positions
    -> calculate_portfolio_risk()（使用账户 total_assets 与保存的 position_ratio）
```

| 字段 | 复现值 | 来源文件/表 | 读取函数 | 更新时间/时点 | 是否权威 | 问题 |
|---|---:|---|---|---|---|---|
| `cash` | 100000 | `paper_account_latest.json` | `AccountRepository.load_account` -> `PortfolioStorage.load_account` | `account.updated_at` | 账户现金权威原始字段 | 与持仓未绑定到共同快照 |
| `account.position_market_value` | 0 | 同上 | `PortfolioService.get_account_summary` | 同上 | 仅历史汇总 | 被直接输出，没有用明细重算 |
| `account.total_assets` | 100000 | 同上 | `PortfolioService.get_account_summary` | 同上 | 仅历史汇总 | 被直接输出，没有做 `cash + positions` 校验 |
| `account_summary.cash_ratio` | 1.0 | 进程内计算 | `get_account_summary` | 同账户汇总 | 不应在不一致时作为权威 | 分母来自陈旧 `total_assets` |
| `positions[0].market_value` | 12000 | `paper_positions_latest.csv` | `PortfolioStorage.load_positions` | `position.updated_at` | 当前持仓明细/价格结果 | 和账户汇总同时返回却未对账 |
| `positions[0].position_ratio` | 0.12 | CSV `market_value / position_ratio` 转换 | `PortfolioStorage._position_from_record` | `position.updated_at` | 当前实现保存/重建值 | 由独立持仓快照得到，未按响应的 `total_assets` 统一计算 |
| `risk.cash_ratio` | 1.0 | 账户对象 | `calculate_portfolio_risk` | 无统一 `as_of` | 非权威派生值 | 风险工具同样信任陈旧账户汇总 |

复现命令在临时目录写入一个账户 JSON 和一个持仓 CSV：账户为 `cash=100000, position_market_value=0, total_assets=100000`，持仓为 `quantity=1000, current_price=12`。只读服务输出为：

```text
state.summary = {
  position_count: 1,
  cash: 100000.0,
  total_assets: 100000.0,
  position_market_value: 0.0,
  cash_ratio: 1.0,
}
position.market_value = 12000.0
position.position_ratio = 0.12
risk.cash_ratio = 1.0
```

这完整复现了症状，未接触生产文件。

### 2.2 代码级原因与权威口径

| 位置 | 确定事实 | 对症状的影响 |
|---|---|---|
| `portfolio/storage.py:130-182` | `save_account()` 与 `save_positions()` 分别写数据库与独立 latest 文件；交易引擎按账户、持仓、订单顺序调用三次保存。 | 中断或交错更新可以留下不同批次的 latest 文件。 |
| `portfolio/storage.py:155-198` | 读取优先本地 latest 文件，再回退数据库；账户与持仓没有共用 snapshot id。 | 可把不同来源/批次的文件组合在一起。 |
| `portfolio/schemas.py:138-170` | `PaperPosition` 不含 `account_id`、`trade_date` 或 `snapshot_id`。 | 当前读取层不能验证持仓属于目标账户或同一时点。 |
| `agent/services/portfolio_service.py:get_account_summary` | 直接取 `account.position_market_value`、`account.total_assets`、`cash / total_assets`。 | 陈旧汇总原样进入账户摘要。 |
| `agent/services/portfolio_service.py:get_current_positions` / `get_position_weights` | 单独读取持仓；权重直接取 `position_ratio`。 | 明细、权重和摘要的分母可不同。 |
| `agent/services/portfolio_risk_service.py:analyze_current_risk` | 先使用存储风险报告；否则独立第二次加载账户/持仓。 | 风险结果不保证来自 State 工具返回的那一个逻辑快照。 |
| `portfolio/portfolio_risk.py:calculate_portfolio_risk` | 初始总资产取账户 `total_assets`，`_position_ratio` 优先采用保存的 ratio。 | 在陈旧汇总下，风险数值与持仓价值可冲突。 |
| `portfolio/storage.py:439-567` | 日快照已在写入时重算市值并检查一致性，但 `portfolio_state` 不读取日快照。 | 已有安全口径未被 Agent 当前状态工具复用。 |

权威口径判定为 **D：当前存在多个来源，读取阶段必须归一化**。在只读查询中，权威派生字段应由同一组经过身份/时点校验的当前持仓明细计算：

```text
position_market_value = sum(valid position market_value)
total_assets = cash + position_market_value
cash_ratio = cash / total_assets
position_ratio = position.market_value / total_assets
```

原始账户记录和原始持仓记录仍保留，只读响应以明确的 source metadata 表示计算来源与任何陈旧字段差异。对于跨用户、跨账户或跨时点输入，不能静默混合，必须返回结构化不一致错误。现金账户（无有效持仓）仍应得到 `position_market_value=0`、`total_assets=cash`、`cash_ratio=1`。

### 2.3 实际开发数据检查

本次只读检查的现有开发输出当前是自洽的，不能作为症状的发生批次：

| 用户 | 账户时间 | 持仓时间 | 账户持仓市值 | 明细市值合计 | 总资产 |
|---|---|---|---:|---:|---:|
| `cht` | 2026-07-17 09:31:41 | 2026-07-17 09:31:41 | 210049.0 | 210049.0 | 299008.2339 |
| `default` | 2026-07-17 09:32:09 | 2026-07-17 09:32:09 | 220385.0 | 220385.0 | 298012.5692 |

这说明问题不是当前两个 latest 文件已经损坏，而是服务层没有防止被观察到的失配状态。根因由上述临时目录复现和调用链确定。

## 3. Replan 证据链

| 阶段 | 产生动作 | 消费模块 | 是否被消费 | 计数变化 | 终止条件 | 问题位置 |
|---|---|---|---|---|---|---|
| Tool / Observe | Phase 15 `ReplanPolicy.build_replan_decision()` 生成 `REQUESTED` | `agent/react/integration.py` | 否，只保存观察并发消息 | 无；调用没有 `record=True` | Policy limiter 仅在显式 `record=True` 才增量 | `integration.py:222-258` |
| Completion | `GoalObserveResult.next_action = replan_readonly` | 无 | 否 | 无 | `executor.py` 已完成多任务执行 | `executor.py:4424-4438` 仅赋值 `result_dict["llm_completion"]` |
| Critic | `CriticPolicy.decide_action()` 返回 `CriticAction.REPLAN_READONLY` | 无 | 否 | 无 | Reflection 位于最终答案之后 | `critic_policy.py:220`、`executor.py:4634-4650` |
| Multi-task 通用恢复 | `_replan_directive()` 读取失败任务的 `data.next_action` / 错误码 | `multi_task_executor` | 是，但只用于已失败的任务、RAG/MCP fallback | `replan_count += 1` | `MAX_REPLAN_ROUNDS=2` 和预算 | `multi_task_executor.py:1056-1230`、主循环 |
| 终端空依赖 | `_apply_terminal_replan_for_empty_dependencies()` | `multi_task_executor` | 仅改为 skip | 仍会无条件 `+1` | 未与 `MAX_REPLAN_ROUNDS` 同一守卫 | 主循环终端分支 |

实际顺序是：

```text
TaskPlan 执行（multi_task_executor）
  -> 当前内建任务失败恢复（可执行）
  -> ToolResult
  -> Completion 评估（仅写 llm_completion）
  -> Phase15 observation / message（仅发布 ReplanDecision）
  -> 最终答案
  -> Critic（仅保存、发布 CriticResult）
  -> 返回响应
```

而需求需要的顺序是：

```text
Task 执行 -> Observe -> Completion / Critic -> 统一 Replan Action
-> 限额检查 -> 新只读 TaskPlan -> 安全校验 -> replan_count + 1 / audit
-> 执行 -> 再次 Observe / Completion / Critic
```

确定根因：

- 动作有两种不兼容表示：Completion 是小写字符串 `replan_readonly`，Critic 是大写枚举值 `REPLAN_READONLY`；当前没有规范化入口。
- `execute_multi_intent_plan()` 在 Completion 和 Critic 之前返回；这两个后置阶段没有回调或续跑 API。
- Phase15 ReplanPolicy 是“决定/记录消息”组件，不是执行器；且 `integration.py` 构建决定时未记录 limiter。
- `multi_task_executor` 只对失败 TaskResult 的受限指令或内建 RAG/MCP fallback 再执行，完全不读取 `llm_completion` 或 `reflection.action`。
- 单任务路径在 executor 的观察结论中直接写 `next_action=finish`（成功）或 `fail`（失败），不存在 Replan 消费；多任务路径仅有另一套局部恢复逻辑。
- 当前终端空依赖分支可在通用恢复循环之后额外增加计数，未统一使用同一上限检查。因此不能将它作为新 Replan 的计数权威。

## 4. TopK 证据链

| 层级 | 接收到的值 | 输出值 | 默认值 | 覆盖条件 | 代码位置 |
|---|---:|---:|---:|---|---|
| 页面 | `default_topk`（页面默认 10） | `top_k=int(default_topk or 50)` | 10 / 隐式 50 | `default_topk` 为假值时回退 50 | `app/pages/ai_agent.py:1551-1559,1950-1957` |
| 请求入口 | 参数 `top_k` | `route_context.default_top_k` | 函数默认 50 | 调用者未传入时即为 50 | `agent/executor.py:3127-3138,3393-3400` |
| 用户参数 | `extract_parameters()` 提取 `top_k` | `params["top_k"]` | 无 | 仅用户文本带 TopN / 前N | `agent/parameter_extractor.py:95-105,191-204` |
| 规则 fallback 推荐 | 无显式“十/top10”时 | TaskPlan `ranking.top_k=50` | 50 | 文本没有触发固定的 Top10 字符串 | `agent/intent_decomposition/rule_fallback.py:343-357` |
| 规则 fallback 排名 | 无显式“十/top10”时 | TaskPlan `ranking.top_k=50` | 50 | 同上 | `rule_fallback.py:362-368` |
| 兼容规划 | 推荐任务 | TaskPlan `ranking.top_k=10` | 固定 10 | 无旧拆解任务时 | `agent/goal_planning.py:345-364` |
| 未接入解析器 | 查询/TaskPlan/默认值 | 会返回适当数值 | 默认 10 | 函数没有任何调用点 | `agent/executor.py:_requested_top_k`，`rg` 仅命中定义 |
| Executor 实际选择 | `params.top_k or request top_k` | `requested_top_k` | `top_k or 50` | **不读取当前 ranking TaskPlan 参数** | `agent/executor.py:3606-3616` |
| DAG 参数解析 | task 参数 | 保留 task `top_k`，缺失才 `setdefault(default_top_k)` | request default | 已有 50 不会被替换 | `agent/orchestration/argument_resolver.py:resolve_task_arguments` |
| Tool adapter | `args.top_k or context.default_top_k or 50` | 服务 `top_k` | 50 | 参数为空或假值时回退 | `agent/tools/market_analysis_adapters.py:40-46` |
| Ranking 服务 | `top_k` | `rows[:int(top_k)]` | 50 | 未指定股票且非 all | `agent/services/market_analysis_service.py:238-286` |
| 数据读取 | 全 CSV | 之后切片 | 无 | `load_latest_ranking()` 调用 DataFrame 全量读取 | `market_analysis_service.py:73-80,126-132` |

`default_top_k=10 -> rule fallback TaskPlan top_k=50 -> ArgumentResolver 保留 50 -> ranking adapter 请求 50 -> 服务返回 50` 是已确定的覆盖路径。

应统一为：

```text
用户显式 top_k
> 当前 TaskPlan.parameters.top_k
> 请求级 default_top_k
> 工具默认值
> 系统最终兜底
```

服务返回数必须满足 `returned_count <= requested_top_k`。目前服务虽切片保证返回不超指定值，却会先全量读 CSV；修复会在本地 CSV 无筛选场景使用读取上限，并保留模型筛选时完整读取后精确截断的兼容说明。

## 5. 根因结论

### 5.1 持仓状态

- **直接根因**：State/Risk 工具把独立读取的账户历史汇总和持仓明细拼接，未重算/校验汇总。
- **系统性根因**：Latest 文件与数据库是多来源且分开保存的模型，却没有只读统一快照模型、身份键和时点键。
- **受影响范围**：`portfolio_state`、`portfolio_risk`、AI Agent Context/最终聚合以及依赖这些结果的只读推荐。
- **现有测试未发现的原因**：现有测试分别验证存储、风险或工具能读到数据，没有构造陈旧账户汇总加有效持仓、跨账户、跨时点和风险/State 同快照断言。

### 5.2 Replan

- **直接根因**：Completion/Critic 动作产生在执行结束后，未映射到任何续跑执行入口。
- **系统性根因**：ReplanDecision、Completion 字符串、Critic 枚举与多任务恢复机制并存，没有统一动作协议、计数器、审计记录和循环控制器。
- **受影响范围**：所有需要缺失产物补救的单任务、多任务及 Phase16 Critic 路径；不影响 WriteGateway 的写边界，但现有 Replan 也不能证明持续阻断写任务。
- **现有测试未发现的原因**：Phase15 验证 policy 可生成决定、Phase16 验证 Critic 可生成枚举、multi-task 验证特定 RAG/MCP fallback；没有端到端测试“产生动作 -> 新计划 -> 再执行 -> 计数/audit”。

### 5.3 TopK

- **直接根因**：`rule_fallback.py` 依据关键词硬编码 50，且 Executor 未使用其已有的 TaskPlan-aware 解析函数。
- **系统性根因**：页面、请求入口、fallback、任务参数、ArgumentResolver、adapter 和服务各自有默认值/强制值，没有唯一优先级解析器。
- **受影响范围**：规则 fallback 的 Ranking、推荐、市场证据，以及单任务调用的请求默认值传递。
- **现有测试未发现的原因**：现有测试覆盖 Top10 策略配置和部分 Ranking 功能，没有跨 UI/request/TaskPlan/adapter/服务的 exact-limit 断言。

## 6. 修改方案

| 目标 | 准备修改的文件 | 准备新增测试 | 兼容策略 | 数据迁移 | 回滚 |
|---|---|---|---|---|---|
| 统一模拟盘只读快照 | 新增 `portfolio/portfolio_snapshot.py`；修改 `agent/services/portfolio_service.py`、`agent/services/portfolio_risk_service.py`、`portfolio/portfolio_risk.py` | `test_portfolio_snapshot_consistent.py`、`test_portfolio_snapshot_recomputes_stale_summary.py`、`test_portfolio_snapshot_rejects_cross_account.py`、`test_portfolio_snapshot_rejects_cross_time_snapshot.py`、`test_portfolio_risk_uses_normalized_snapshot.py`、`test_portfolio_state_output_is_self_consistent.py`、`test_empty_positions_cash_only_account.py`、`test_position_ratio_uses_total_assets.py`、`test_portfolio_rounding_tolerance.py` | 保留账户/持仓原始字段和现有响应键；新增 consistency/source metadata，仅读响应覆盖陈旧派生字段 | 无；不改历史原始文件 | 恢复服务调用旧逻辑即可，原始账户/持仓文件未被改写 |
| 统一并执行只读 Replan | 新增 `agent/replan_execution.py`；修改 `agent/executor.py`、`agent/orchestration/multi_task_executor.py`，必要时统一 `agent/react/integration.py` | `test_replan_readonly_is_consumed.py`、`test_critic_replan_is_consumed.py`、`test_completion_replan_is_consumed.py`、`test_replan_count_increments.py`、`test_replan_audit_written.py`、`test_replan_never_exceeds_limit.py`、`test_replan_limit_zero.py`、`test_replan_limit_one.py`、`test_replan_limit_two.py`、`test_replan_blocks_write_tools.py`、`test_replan_stops_when_goal_completed.py`、`test_replan_exhausted_returns_partial.py`、`test_replan_no_infinite_loop.py` | Replan 仅允许现有 READ/ANALYZE/无业务写 PREVIEW；保留既有 RAG/MCP 任务恢复，并将其纳入同一计数/audit 语义 | 无 | 保留旧任务结果；新循环可以由常量/上下文限额设为 0 停用 |
| 精确 TopK | 新增/集中 `resolve_requested_top_k`（放在 `agent/orchestration/argument_resolver.py`）；修改 `executor.py`、`rule_fallback.py`、`market_analysis_adapters.py`、`market_analysis_service.py`、`app/pages/ai_agent.py` | `test_top_k_explicit_user_value.py`、`test_top_k_task_value.py`、`test_top_k_request_default.py`、`test_top_k_tool_default.py`、`test_top_k_no_fallback_override.py`、`test_top_k_reads_exact_limit.py`、`test_top_k_returned_count_not_exceed_requested.py`、`test_top_k_two_reads_two.py`、`test_top_k_ten_reads_ten.py`、`test_top_k_fifty_reads_fifty.py`、`test_top_k_insufficient_data.py`、`test_top_k_invalid_value.py`、`test_top_k_argument_resolver_preserves_value.py`、`test_top_k_rule_fallback_preserves_request_default.py` | 继续接受 `int`、数字字符串及既有 `all` 行为（仅兼容工具直接调用）；Agent 正常请求严格使用已解析正整数 | 无 | 保留旧服务签名和默认值，回退只影响解析函数调用点 |

## 7. 风险

- 将陈旧账户汇总改为只读重算会改变此前不一致响应中的展示数字；这是必要的正确性变化，原始记录不改写。
- 严格拒绝跨账户/跨时点输入可能让过去静默返回的错误数据转为结构化失败；调用方必须显示安全限制。
- Completion/Critic Replan 增加额外只读工具调用，因此必须严格限制总轮数、预算、任务数量及 WRITE/确认类参数。
- TopK 改为按需读取会降低过度读取，但任何下游隐式依赖 50 条的数据都必须在 TaskPlan 中显式要求所需数量；本次不改变业务排名顺序。
- 所有页面仍保留模拟盘免责声明，且不接入真实交易。

## 8. 排查阶段验证

| 命令/检查 | 结果 |
|---|---|
| `Get-Content AGENTS.md`、`PROJECT_STRUCTURE.md`、`PROJECT_FILE_DIRECTORY.md` | 已完整读取并遵守 D 盘虚拟环境、只读 Phase A 和模拟盘边界。 |
| `Get-Content C:\Users\86195\Downloads\Codex_Prompt_先排查后修复_持仓一致性_Replan_TopK.md` | 已完整读取。 |
| 代码搜索：`rg` 覆盖 executor、goal planning、router、intent decomposition、orchestration、react、reflection、tool engine、portfolio、pipeline、database、AI Agent 和 tests | 已建立上述真实 import/call 路径。 |
| 临时目录状态复现（D 盘 `.venv\Scripts\python.exe`） | 成功复现账户 0 市值与持仓 12000 市值同时输出，且风险现金占比仍为 1。 |
| 只读检查 `outputs/portfolio/{cht,default}` | 当前两份开发 latest 文件同时间戳且数值自洽；未修改。 |
| `D:\stock_daily_app\.venv\Scripts\python.exe -m pytest -q tests\unit\test_portfolio_risk.py tests\unit\test_portfolio_storage.py tests\unit\test_agent_multi_task_async.py tests\unit\test_phase15_replan_policy.py tests\unit\test_phase16_critic_engine.py tests\unit\test_phase10_goal_planning.py` | 35 passed，2 failed；失败均为既存 Phase10 基线：`test_pure_portfolio_state_query_uses_validated_fast_path`（当前 action 为 `query`）与 `test_observe_marks_tool_success_but_goal_incomplete_as_partial`（当前 status 为 `missing`）。 |

## 9. Phase A 门禁结论

- 三个问题均有具体根因：**通过**。
- 每个根因均定位到文件、函数、字段和执行顺序：**通过**。
- 账户/持仓权威口径、Replan 消费缺口、TopK 覆盖位置均已确认：**通过**。
- 根因报告已保存：**通过**。
- Phase A 未修改业务代码、数据库结构或生产数据：**通过**。

可以进入 Phase B 修复。
