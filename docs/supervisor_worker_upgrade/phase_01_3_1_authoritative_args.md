# Phase 01.3.1：权威运行参数绑定与语义输入边界

## 问题

真实本地模型计划把 `focus_ref_ids` 写入了 `inputs`，而 W01 的公开运行合同要求它位于 `args`。这导致计划在依赖编译前被拒绝。同时，模型为普通实体分析错误扩展了组合影响和组合风险 Worker。

## 修改

- `focus_ref_ids`、`user_id`、`reply_language`、`as_of_time` 等权威运行参数由代码根据 Worker 卡片绑定。
- MainAgent 不再负责复制这些已知值；公开 Worker 卡会显示 `runtime_bound_args`。
- `inputs` 仅允许 `from_task_id + expected_output_type` 的上游 WorkerResult 引用。
- 程序仍只从 MainAgent 明确声明的 `inputs` 推导 `dependency_task_ids`，不会新增 Worker 或依赖边。
- 强化最小 Worker 选择边界：独立实体分析不扩展到组合、影响、风险或策略任务。

## 保持不变

- MainAgent 仍直接选择 Worker 并生成完整 Worker DAG。
- Validator 只接受或拒绝，不修改 DAG。
- 本地 LLM timeout、模型配置和 Tool 私有边界不变。
