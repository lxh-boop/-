# Agent 流程、Replan、资产口径与故障提示修复报告

验收日期：2026-07-18  
范围：模拟盘资产快照、Agent 流程完整性、Completion/Reflection Replan、用户可见故障状态与 Streamlit 页面。

## 1. 结论与边界

已完成资产口径澄清、确定性完整性校验、带进展审计的只读 Replan、逻辑错误的不可写故障状态及页面提示。所有 Python 命令均使用 `D:\stock_daily_app\.venv\Scripts\python.exe`；没有调用实盘、券商或外部交易写入。

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## 2. 112000 与 122000

结论为 **B：不同夹具**，不是同一资产快照的计算冲突。

| 场景 | 现金 | 持仓市值 | 总资产 |
| --- | ---: | ---: | ---: |
| 单一持仓：1000 × 12 | 100000 | 12000 | 112000 |
| 两个持仓：1000 × 12 + 1000 × 10 | 100000 | 22000 | 122000 |

两者均使用 `cash_semantics=uninvested_cash`：现金是未投入持仓的可用资金。唯一公式为 `total_assets = uninvested_cash + sum(active_position.quantity * current_price)`，不会从现金重复扣减持仓，也不会重复加入持仓市值。

## 3. 资产快照实现

- `portfolio/portfolio_snapshot.py` 现在输出 `cash_semantics`、`calculation_trace`、`snapshot_id`。
- 状态、风险与预览能够透传同一快照 ID；风险服务可直接接收已读取的组合状态，避免口径漂移。
- 跨用户、跨账户、跨显式快照时间、负现金/负数量、缺失价格、NaN/Inf 或不可导出的总资产会被拒绝。
- 被拒绝快照带 `status=logic_error`、`error_code=portfolio_snapshot_inconsistent` 及 `safe_to_continue/safe_to_write=false`；模拟盘预览因此不会生成建议或确认计划。

## 4. 资产可追溯性与回归

新增测试覆盖：112000/122000 夹具、未投资现金、旧汇总字段、总资产无双计数、计算追踪、状态与风险共享快照 ID、异常快照阻断推荐。

资产相关新增与原有回归结果：`18 passed in 100.01s`；场景 A–F 与资产用例补充结果：`14 passed in 2.43s`。

## 5. 流程完整性安全门

新增 `agent/logic_integrity.py` 和 `LogicIntegrityResult`。它不调用 LLM，按事实检测：

- 组合状态与风险快照冲突；
- 显式完成契约或必需产物缺失；
- 任务计划/结果数量异常（仅在同一普通多任务执行路径强制）；
- Completion 在任务失败时虚报成功；
- Replan 请求未执行、轮次计数不符、无进展或已耗尽；
- 逻辑错误路径的写计划。

逻辑错误会阻断继续、可靠推荐、Replan、审批和写入；受确认保护的一次性模拟盘预览保留其独立工作流，不会被不兼容的普通多任务计数规则误杀。

## 6. Replan 进展与签名

`agent/replan_execution.py` 的每轮审计包含：轮次、触发源、缺失项前后、计划与工具调用、执行任务、产物前后、新/变更产物、计划/结果签名、进展状态和停止原因。

- 计划签名归一化工具、参数与预期；结果签名排除轮次生成的任务 ID、时间戳与敏感字段。
- Completion 和 Critic 对同一请求只实际执行一次，后续记录为去重。
- 相同计划、相同结果、无新有效证据、上限、目标完成、预算耗尽、逻辑错误或写任务都会立即停止。
- `replan_count` 只在实际调用安全只读计划后递增。

完整性与 Replan 测试结果：`33 passed in 10.49s`。

## 7. 用户可见故障状态

逻辑错误返回：

```text
当前功能出现异常，暂时无法可靠完成该请求，请等待后续版本更新完善。本次未执行任何写操作。
```

英文等价消息也已提供。状态包含 `feature_unavailable`、`error_code`、`user_visible=true`、`safe_to_continue=false`、`safe_to_answer=true`、`safe_to_write=false`、`retryable=false`、`requires_version_update=true` 和 `no_write_performed=true`。该结果由确定性代码生成，LLM 无法覆盖。

`app/pages/ai_agent.py` 会显示“功能状态：暂不可用（逻辑错误）”、错误代码和“写操作：未执行”。故障状态测试：`10 passed in 6.71s`。

## 8. 真实执行器、确认与回归

以下回归已通过：

- 稳定持仓只读推荐；
- 完整模拟盘稳定调仓预览、确认、拒绝、过期、状态冲突和事务回滚；
- 组合风险归一化；
- Completion/Critic Replan 集成。

结果：`20 passed in 122.39s`。

连续三次真实中文请求“把我现在的持仓调整得更稳健”均成功，均生成待确认的模拟盘计划，均未进入 `feature_unavailable`；没有直接写入持仓。

## 9. 场景 A–F

| 场景 | 结果 |
| --- | --- |
| A 正常稳定推荐 | 保持可用，生成只读分析或待确认模拟盘计划。 |
| B 资产不一致 | 进入 `feature_unavailable`，不写入。 |
| C 状态/风险快照 ID 冲突 | 确定性阻断。 |
| D Replan 产生新证据 | 可继续，审计记录差异。 |
| E Replan 无进展 | 停止并进入逻辑错误路径。 |
| F Replan 耗尽 | 停止并进入逻辑错误路径。 |

## 10. 文档与项目结构

已更新 `PROJECT_FILE_DIRECTORY.md` 和 `PROJECT_STRUCTURE.md`，加入资产计算追踪、快照 ID、完整性安全门、Replan 签名/停止规则以及本报告与复核报告入口。

## 11. 全量测试说明

最终命令为：

```powershell
& D:\stock_daily_app\.venv\Scripts\python.exe -m pytest tests\unit -q
```

该轮在 `724.1s` 到达执行超时，未输出断言失败、通过数或最终汇总，因此不能声称全量测试全绿。它不是本次代码产生的已定位断言失败；所有任务相关分组、真实执行器闭环和三次稳定性运行均已单独通过。建议后续以分片或 CI 无超时环境完成全量套件并记录精确汇总。

## 12. 部署验收

部署使用项目虚拟环境解释器，服务只监听 `127.0.0.1:8501`。部署前会清理该端口全部监听者，再启动 Streamlit 并进行 HTTP 与页面验证。
