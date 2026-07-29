# Phase 01.4：W02 内部系统数据查询与强类型 Handoff

## 本次解决的问题

此前普通证券分析只执行 W01 外部证据检索与 W06 报告生成，因此最终回答主要是新闻、公告总结，未读取项目已有的模型预测、排名、模型指标、回测、持仓、账户和用户画像。

## 修改前流程

```text
分析600519
→ W01 外部新闻/公告证据
→ W06 最终报告
```

Worker 间通过 `dependency_results` 传递统一结果，但下游仍可能从通用 `findings` 或 `data` 中按字段名寻找数据，缺少任务级输出合同和显式输入绑定。

## 修改后流程

```text
分析600519
→ W01 外部证据 ─────────┐
                         ├→ W06 最终报告
→ W02 内部模型预测 ─────┘
```

W01 与 W02 无依赖，可并行执行。W06 通过：

```text
输入角色 + from_task_id + expected_output_type
```

获得经过合同校验的 `resolved_inputs`，不再依赖模糊字段搜索。

## W02 新边界

W02 的稳定 Worker ID 和现有运行时 `agent_id=PORTFOLIO_ANALYST` 保持不变，公开角色调整为 `INTERNAL_SYSTEM_RETRIEVER`。

W02 只负责只读查询本系统内部权威数据：

- 单证券模型预测；
- 最新预测排名；
- 模型指标；
- 回测摘要；
- 当前选定策略；
- 当前组合和持仓；
- 账户资金状态；
- 用户画像。

W02 不负责：

- 外部新闻、公告或研报检索；
- 组合风险结论；
- 新闻影响判断；
- 买卖建议；
- Proposal 或任何写操作。

## 任务级合同

同一个 W02 可以在一个 DAG 中出现多次，但每个节点必须声明独立 `task_type` 和对应输出类型。例如：

| task_type | output_type |
|---|---|
| `query_stock_prediction` | `ModelPredictionResult` |
| `query_latest_ranking` | `RankingResult` |
| `query_model_metrics` | `ModelMetricsResult` |
| `query_backtest_summary` | `BacktestSummaryResult` |
| `query_selected_strategy` | `SelectedStrategyResult` |
| `query_portfolio_state` | `PortfolioAnalysisResult` |
| `query_account_state` | `AccountStateResult` |
| `query_user_profile` | `UserProfileResult` |

## 强类型 WorkerResult

`GraphWorkerResult` 新增：

- `payload_schema`；
- `payload_version`；
- `payload`。

保留 `data` 作为兼容字段。旧 Worker 只写 `data` 时，运行时自动同步为 `payload`，因此不破坏既有链路。

## 显式输入绑定

Runtime 根据任务声明的 `inputs`，严格校验：

- 上游任务是否存在；
- 实际 `output_type` 是否等于 `expected_output_type`；
- 消费者输入角色是否接受该类型；
- Payload Schema 和版本；
- 来源 task_id、证据引用和 Artifact 引用。

结果绑定到 `resolved_inputs[role]`，下游 Worker 不需要在全部 `findings` 中猜测字段来源。

## 消息系统边界

业务结果仍由 Coordinator 当前运行内存中的 `results` 权威保存，并按依赖传给下游。MessageBus 不承担大 Payload 运输，只发布 `WORKER_RESULT_AVAILABLE`：

- task_id；
- status；
- output_type；
- payload_schema/version；
- 摘要；
- GraphRef、EvidenceRef 和 ArtifactRef。

这样避免大结果重复序列化和日志膨胀，同时保留审计与消息追踪能力。

## 未修改

- MainAgent 仍直接选择 Worker 并生成完整 Worker DAG；
- 程序不增加、删除、拆分、合并、替换或重连 Worker 节点；
- Validator 仍只接受或拒绝；
- `dependency_task_ids` 仍只从 `inputs.from_task_id` 编译；
- W01 仍负责外部证据；
- W03、W04、W05、W06、W07 的核心职责不变；
- 不修改 LLM 模型、超时、重试配置；
- 不执行真实交易或业务写入。
