# 稳健持仓流程修复与量化 Benchmark 报告

更新日期：2026-07-18

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## 结论

稳健持仓建议链路已收敛为“约束优先、终止优先、只读恢复、可审计最终回复”的流程。正式离线 Benchmark 共 84 个用例、300 次执行，全部通过；未授权写入、审批绕过、Replan 越限和 TopK 超读均为 0。

## Phase 0：真实链路基线

完整复现见 [STABLE_PORTFOLIO_REPAIR_BASELINE.md](STABLE_PORTFOLIO_REPAIR_BASELINE.md)。修复前，请求“推荐一个更稳健的持仓”会出现：

- 用户画像单票上限为 8%，却产生 70% 单票目标；
- 行业覆盖率为 0 时仍以“参考”方式继续；
- Completion 已要求 `report_limitation`，Critic 仍触发第二轮 `REPLAN_READONLY`；
- 未显式指定数量时读取 50 条排名；
- 最终回复可能把无效目标组合表述为成功建议。

## 已实现的流程约束

### LLM 预算与保留安全边界

`agent/runtime_reliability.py` 新增 `ENABLE_LLM_BUDGET_LIMITS = False`。默认关闭的仅是 LLM token/call 限额，不是将阈值调大。工具调用数、运行步骤、超时、重试、熔断、只读 Replan 上限、写入确认、审批和无进展停止仍会执行。诊断场景可显式将 `RuntimePolicy.enable_llm_budget_limits=True` 打开。

### 统一 Replan 状态与审计

`agent/replan_execution.py` 提供共享状态：`replan_count`、`replan_limit`、`executed_rounds`、`attempted_rounds` 和 `replan_audit`。实际执行开始前才增加执行轮次；重复、终止、预算耗尽、不安全、超限和无安全计划仅记为尝试，不消耗执行轮次。

每项审计包含轮次、触发源、缺失项前后、计划/结果签名、计划和实际任务、变化输出、进展、停止原因、请求/执行/完成时间。Completion/Critic 后置恢复与多任务执行上下文均携带同一状态对象。

### 终止状态优先级

`logic_error` / `feature_unavailable` 优先于 Completion、Critic、Replan、继续和成功报告。终止时：

- Completion 返回确定性的 `next_action=report_limitation`，不调用 Completion LLM；
- Critic 返回 `BLOCK_AND_REPORT`，记录被抑制的 `REPLAN_READONLY`；
- 不创建计划、不请求审批、不执行写入，最终回复不能被 LLM 文案覆盖；
- 目标组合存在不可验证行业约束等非可修复问题时，会进入可靠性终止路径。

### 目标组合约束

`portfolio_comparison_tools.py` 对首次设计和构造前校验均执行：

- 证券候选、重复代码、负权重、非正权重、现金范围和总权重会计；
- 目标持仓数量一致性；
- 用户画像/显式风险约束的单票上限，返回证券代码、观测权重、允许上限和约束来源；
- 行业上限；行业元数据不完整时返回 `industry_constraint_unverifiable`，不宣称合规；
- 文案声称符合单票限制、实际却违反时返回 `design_explanation_conflict`；
- 验证器不裁剪或重写 LLM 权重，只产生可审计的错误反馈。

### 按需 TopK

`agent/top_k.py` 的业务优先级为：用户显式值 → TaskPlan 值 → 目标持仓数 × 候选冗余系数 → 请求默认值 → 工具默认值 → 系统兜底。默认候选冗余系数为 2.0，默认目标持仓数为 10，故没有明确指定数量的稳健组合建议读取 20 条候选，而不是隐式读取 50 条。排名适配器使用解析后的精确数量作为源读取上限。

### 最终回复审计

新增 `MessageType.FINAL_RESPONSE`。`agent/executor.py` 在返回前写入独立事件，字段包括 run/conversation ID、最终状态、消息来源与模板、逻辑完整性、Completion、Critic、Replan、写入安全、审批状态和响应哈希；不包含 API Key、Token 或确认 Token。

## 实测验证

所有命令均使用项目虚拟环境解释器：

```powershell
& D:\stock_daily_app\.venv\Scripts\python.exe -m compileall -q agent\runtime_reliability.py agent\replan_execution.py agent\logic_integrity.py agent\executor.py agent\top_k.py agent\orchestration\argument_resolver.py agent\orchestration\multi_task_executor.py agent\tools\portfolio_comparison_tools.py agent\communication
& D:\stock_daily_app\.venv\Scripts\python.exe -m pytest -q tests\unit\test_runtime_reliability_fault_injection.py tests\unit\test_stable_portfolio_workflow.py tests\benchmark\test_stable_portfolio_benchmark.py
```

结果：编译通过；既有运行时/Replan/完整性/TopK 组、目标组合合同和新增 Benchmark 合计 `77 passed`。

完整 `tests/unit` 已按单独长时分片执行，结果为 `1021 passed, 13 failed`（769.54 秒）。失败项均位于既有 Agent Harness、旧多 Agent/MCP 断言、日期敏感的模拟盘确认及旧 Phase 7/10/11 路由合同；其中 Harness 在 2026-07-18 的非交易日得到 `non_trading_day`，Playwright 另因本机未安装 Chromium 无法启动。这些失败不属于本次稳健持仓链路的回归；本次直接覆盖组保持全绿。完整失败清单和环境限制已在本次执行日志中保留，后续应由对应的旧流程维护任务处理。

隔离临时数据库的真实入口复验中，稳健持仓请求的结果为 `feature_unavailable`、`safe_to_write=false`、`replan_count=0`，最终审计事件的 `message_source=deterministic_feature_unavailable`。其候选读取为 `top_k=20`，没有写入操作。该复验不调用真实交易接口，也不写入生产模拟盘。

## Benchmark 结果

正式运行：

```powershell
& D:\stock_daily_app\.venv\Scripts\python.exe benchmarks\agent\run_stable_portfolio_benchmark.py --output-dir outputs\benchmarks\agent
```

结果文件：

- `outputs/benchmarks/agent/stable_portfolio_raw_results.jsonl`
- `outputs/benchmarks/agent/stable_portfolio_metrics.json`
- `outputs/benchmarks/agent/stable_portfolio_metrics.csv`
- `outputs/benchmarks/agent/stable_portfolio_benchmark_report.md`

| 指标 | 结果 |
|---|---:|
| 用例数 | 84（A–F 各 14） |
| 总执行次数 | 300 |
| 总通过率 | 100% |
| Intent 准确率 | 100% |
| Replan 成功率 | 100% |
| 约束命中率 | 100% |
| TopK 精确读取率 | 100% |
| 未授权写入 | 0 |
| 审批绕过 | 0 |
| Replan 越限 | 0 |
| TopK 超读 | 0 |
| 发布门禁 | 通过 |

类别 A–F 覆盖 Intent/TopK、单票限制、行业限制、只读 Replan、终止与写入安全、FINAL_RESPONSE 合同。每类前 4 个离线 LLM 合同场景运行 5 次，其余确定性场景运行 3 次。离线合同场景不会调用真实 LLM 提供方；这是可重复的发布防线，不应误解为实时模型质量评估。

## 可恢复运行

三种可实际使用的恢复方式：

1. 自然语言：继续运行稳健持仓 benchmark。
2. CLI：`& D:\stock_daily_app\.venv\Scripts\python.exe benchmarks\agent\run_stable_portfolio_benchmark.py --output-dir outputs\benchmarks\agent --resume`
3. API：`run_benchmark(output_dir="outputs/benchmarks/agent", resume=True)`。

`--resume` 会读取现有 raw JSONL，跳过已完成的 `(case_id, iteration)`，保留原始结果并重新生成聚合指标与报告。
