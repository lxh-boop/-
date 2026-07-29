# Phase 01.4 文件说明

## 新增

- `agent/worker_tools/internal_system.py`：W02 私有只读内部数据工具。
- `agent/collaboration/workers/internal_system.py`：W02 任务执行与强类型结果标准化。
- `tests/unit/test_supervisor_worker_phase_01_4_internal_system_data.py`：任务合同、预测查询、显式绑定与报告回归测试。
- `scripts/refactor/check_supervisor_worker_phase_01_4.py`：架构静态检查。
- `scripts/refactor/supervisor_worker_phase_01_4_acceptance.py`：W01/W02/W06 验收。
- `docs/supervisor_worker_upgrade/phase_01_4_internal_system_data_and_typed_handoff.md`：技术说明。
- `COMMIT_MESSAGE_PHASE_01_4.md`：中文 Git 提交说明。

## 修改

- `agent/collaboration/models.py`：任务级合同和强类型 Payload。
- `agent/collaboration/agent_directory.py`：W02 内部数据边界、多任务合同、显式输入解析。
- `agent/collaboration/planner.py`：任务级权威参数绑定及普通证券分析规划说明。
- `agent/collaboration/specialist_runtime.py`：W02 调度、resolved_inputs 与结果消息。
- `agent/collaboration/worker_contracts.py`：Payload 合同校验。
- `agent/collaboration/workers/report_writer.py`：优先消费 resolved_inputs。
- `agent/collaboration/workers/graph_impact.py`、`risk.py`：接收显式输入上下文，保持旧执行兼容。
- `agent/worker_tools/registry.py`、`__init__.py`：注册 W02 私有工具。
- `agent/communication/message_types.py`、`message_router.py`：增加结果可用消息。
- `scripts/refactor/check_supervisor_worker_phase_01_3_1.py`：更新被 Phase 01.4 替代的最小 DAG 文案检查。
