重构(agent)：接入内部系统数据并强化 Worker 结果合同

将 W02 重构为本系统权威数据查询 Worker，接入模型预测、排名、模型指标、回测、策略、持仓、账户和用户画像等只读能力。

为同一 Worker 的不同任务增加独立任务合同，并在 GraphWorkerResult 中增加强类型 Payload、Schema 和版本信息。

根据 inputs.from_task_id 和 expected_output_type 显式绑定下游输入，避免从通用 findings 中按字段名猜测结果来源；MessageBus 仅传递结果状态、摘要和引用，不承担完整业务数据运输。
