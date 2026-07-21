# Portfolio / Replan / TopK 修复报告

完成日期：2026-07-17  
关联根因报告：[PORTFOLIO_REPLAN_TOPK_ROOT_CAUSE_REPORT.md](PORTFOLIO_REPLAN_TOPK_ROOT_CAUSE_REPORT.md)

> 本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## 结论

三项问题均已修复，且没有对生产模拟盘、数据库或外部服务执行写操作：

1. Agent 组合状态、风险和仓位预览改用统一的只读归一化快照；不再信任可能陈旧的账户汇总字段。
2. Completion 与 Reflection Critic 的 `REPLAN_READONLY` 已有实际、受限、可审计的执行消费者；不会执行写工具，也不会无限重规划。
3. TopK 改为单一优先级解析与按需读取；显式请求 10 不会被规则 fallback 覆盖为 50。

本次还修正了接入过程中发现的两个兼容性问题：不再以 Replan 编排元数据覆盖受确认保护的业务预案；确定性的校验失败不再被 LLM 报告层改写。

## 根因与修复映射

| 根因 | 修复 | 结果 |
|---|---|---|
| 账户汇总与持仓明细独立读取，陈旧的 `total_assets`、`position_market_value`、`position_ratio` 可同时出现在同一响应 | 新增 `portfolio/portfolio_snapshot.py`，校验身份与显式快照时间，并按 `cash + sum(quantity × valid price)` 重算全部派生字段 | 状态、风控、权重和预览使用同一口径；保留原始记录和异常标识，不改写 latest 文件 |
| Completion / Critic 只记录 `REPLAN_READONLY`，没有执行消费者 | 新增 `agent/replan_execution.py`；`agent/executor.py` 在 Completion 与 Critic 后受限消费 | 仅可执行注册表声明的只读工具；轮次、审计、已完成、上限和阻断状态均可追溯 |
| `rule_fallback` 等路径硬编码 `top_k=50`，服务端先全量读后截断 | 新增 `agent/top_k.py`，接入参数解析、规则 fallback、执行器、适配器、服务和页面默认值 | 优先级统一为“用户显式值 → 任务值 → 请求默认值 → 工具默认值 → 系统兜底”；正常 ranking 源读取使用请求的精确行数 |

## 主要实现

- `portfolio/portfolio_snapshot.py`
  - 拒绝跨用户、跨账户和显式快照时间冲突；兼容无显式快照标识的历史 latest 文件。
  - 重算 `position_market_value`、`total_assets`、`cash_ratio`、每项 `position_ratio`。
  - 以 `consistent`、`recomputed_stale_summary`、`missing_account`、`rejected` 等状态返回一致性结论。
- `agent/services/portfolio_service.py`、`agent/services/portfolio_risk_service.py`、`portfolio/portfolio_risk.py`
  - 组合状态、现金、权重、风险统一使用归一化快照。
  - 风险计算不再使用已保存的陈旧风险汇总或已保存的仓位比例。
- `agent/replan_execution.py`、`agent/executor.py`
  - 接受 Completion 的大小写动作和 Critic 枚举动作。
  - 仅对已注册 `OP_READ` 工具构建补救计划；写工具、保护工具和含变更参数的任务均被拒绝。
  - 只在真实只读计划开始执行前增加 `replan_count`，并写入 `replan_audit`；到达上限时保持安全的 partial 状态。
- `agent/top_k.py`、`agent/orchestration/argument_resolver.py`、`agent/intent_decomposition/rule_fallback.py`、`agent/services/market_analysis_service.py`
  - 所有入口复用同一解析器，数值限制为 1–100。
  - 正常无筛选 ranking 请求通过 CSV `nrows` 精确读取所需行数，返回数量不超过请求值。
- `agent/executor.py`
  - Replan 摘要附加在原有业务数据上，不会覆盖 `plan_id`、确认凭证或回滚信息。
  - 只读响应、运行摘要、分解结果和工具调用摘要剔除敏感参数占位；受保护预案的直接结果仍保留同一用户确认所需凭证。
  - 对确定性失败保留可执行的原始提示，避免 LLM 改写一手约束等业务校验结论。

## 验收与验证

| 项目 | 命令 / 场景 | 结果 |
|---|---|---|
| 快照归一化定向测试 | 9 项快照、风险、现金、权重与误差容忍测试 | 19 passed |
| Replan 定向测试 | Completion、Critic、计数、审计、上下限、禁写、终止与无循环测试 | 30 passed |
| TopK 定向测试 | 优先级、非法值、读取行数、返回上限与 fallback 测试 | 26 passed |
| 受确认预案兼容回归 | Phase 3、Phase 16、稳定持仓闭环及 Replan 关键用例 | 16 passed |
| 确定性失败提示与组合预览回归 | 一手约束、Phase 3、稳定持仓闭环、Phase 16 | 13 passed |
| 编译 | `D:\stock_daily_app\.venv\Scripts\python.exe -m compileall -q agent app portfolio pipelines database strategies` | passed |
| 三次稳定性运行 | “推荐一个比现在更稳健的持仓，并说明为什么稳健。”（临时夹具、无 LLM Key） | 三次均为 `multi_intent`、请求 TopK 10、返回 2 条 ranking、总资产 112000、持仓市值 12000、`replan_count=2`、安全 partial |
| 最终完整单测 | `D:\stock_daily_app\.venv\Scripts\python.exe -m pytest tests\unit -q` | **975 passed, 8 failed, 255 warnings，635.24s** |

完整单测中剩余的 8 项失败是本次开始前已存在的 Agent 路由/规划基线问题，且最终轮次没有出现本次修改涉及的快照、风险、Replan、TopK、确认闭环或稳定持仓测试失败：

- `test_agent_harness_runs_repeatable_confirmation_cases`
- `test_stable_recommendation_planner_selects_mcp_when_available`
- `test_readonly_multi_agent_collaboration_records_handoff_and_no_writes`
- `test_phase7_simple_request_uses_rule_without_llm`
- `test_phase7_llm_write_task_is_blocked_and_falls_back`
- `test_pure_portfolio_state_query_uses_validated_fast_path`
- `test_observe_marks_tool_success_but_goal_incomplete_as_partial`
- `test_phase11_legacy_shadow_records_old_and_new_mainline`

## 数据兼容性、迁移和回滚

- 本次无需数据库迁移；未修改 `data/agent_quant.db`、`outputs/portfolio/` 或外部数据源。
- 旧 latest 记录未包含 `account_id`、`snapshot_id`、`as_of_date` 时仍可读取；归一化器以其显示时间诊断，但不会把不同秒的传统 `updated_at` 静默判为跨快照。
- 如果账户汇总已陈旧，返回值会按当前有效持仓重算，因此依赖旧错误总资产的测试或展示会显示正确数值。稳定持仓夹具从 100000 的陈旧汇总口径改为 122000 的归一化口径，相应目标量为 `000001=800`、`600519=900`。
- 回滚代码时，可回退本报告“主要实现”所列文件；没有数据迁移或数据回滚步骤。建议保留根因报告和本报告作为审计记录。

## 风险边界

- 只读 Replan 不调用任何写工具、确认、提交或真实交易接口；模拟盘写操作仍必须走 `WriteGateway → approval → revalidate → commit`。
- 本项目没有连接券商，也不会执行实盘交易。
- 未带强快照标识的历史文件无法被积极证明为同一批次；实现对此保持兼容并显式标示归一化/异常状态。后续若演进存储层，可增加原子 `snapshot_id` 以获得更强的一致性证明。
