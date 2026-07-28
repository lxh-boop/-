# Supervisor–Worker 阶段 01.1：结构化 Worker 合同

## 目标

保持既有流程不变：MainAgent 直接选择 Worker、生成完整 Worker DAG；Validator 只校验；执行器按原图执行；Worker 内部继续使用私有 Tool。

## 本阶段新增

- 7 个 Worker 的稳定 `worker_id`：`W01`～`W07`。
- MainAgent 可见的结构化能力卡：职责、任务类型、输入 Schema、输出 Schema、上游输出合同、非职责、副作用。
- MainAgent 输出结构化 Worker DAG：`task_id`、`worker_id`、`objective`、`task_type`、`args`、`dependency_task_ids`、`expected_output_type`。
- Worker 统一返回带 `output_type`、`data`、`error` 的 `GraphWorkerResult`。
- Worker 内部可读取私有 Tool Schema；MainAgent 看不到私有 Tool。
- Validator 只做通用合同检查，不按具体股票问题写业务规则，不修改 DAG。
- 合同失败时，由现有 LLM JSON repair 丢弃原计划并重新生成完整 Worker DAG。

## 明确未改变

- 不增加 Goal DAG 或 Capability DAG。
- 不增加 Capability Binder。
- 不自动补充、删除、拆分、合并、替换 Worker。
- 不修改本地 LLM timeout 和重试等待时间。
- 不修改 Worker 内部现有业务 Tool 实现。
- 不执行 Git add、commit 或 push。

## Worker 编号

| Worker ID | Runtime Agent ID | 输出类型 |
|---|---|---|
| W01 | EVIDENCE_RETRIEVER | EntityResearchResult |
| W02 | PORTFOLIO_ANALYST | PortfolioAnalysisResult |
| W03 | GRAPH_IMPACT_ANALYST | ImpactAnalysisResult |
| W04 | RISK_ANALYST | PortfolioRiskResult |
| W05 | STRATEGY_GUARD | ReviewedProposal |
| W06 | REPORT_WRITER | FinalReport |
| W07 | SYSTEM_DIAGNOSTIC | DiagnosticResult |
