# Phase 01.4.1 修改文件

## 修改

- `agent/collaboration/models.py`
  - MainAgent 公开合同改为 `args_schema`、`semantic_inputs_schema`；
  - 增加任务级 `default_args`；
  - 保留内部旧 `input_schema` 兼容。
- `agent/collaboration/agent_directory.py`
  - W02 预测与排名默认 `top_k=10`；
  - 补充模型名和日期字段缺省规则。
- `agent/collaboration/planner.py`
  - 增加字段归属预检；
  - 修正 Planner Prompt；
  - 注入精确 Repair 指引；
  - 确定性应用任务默认参数。
- `core/llm/service.py`
  - `generate_json()` 支持可选 `repair_guidance`，不改变原有一次 Repair 策略。
- `tests/unit/test_supervisor_worker_phase_01_1_contracts.py`
- `tests/unit/test_supervisor_worker_phase_01_3_1_authoritative_args.py`
- `tests/unit/test_supervisor_worker_phase_01_4_internal_system_data.py`
- `scripts/refactor/check_supervisor_worker_phase_01_1.py`
  - 更新为新的公开合同名称。

## 新增

- `tests/unit/test_supervisor_worker_phase_01_4_1_planner_contracts.py`
- `scripts/refactor/check_supervisor_worker_phase_01_4_1.py`
- `scripts/refactor/supervisor_worker_phase_01_4_1_acceptance.py`
- `docs/supervisor_worker_upgrade/phase_01_4_1_planner_args_semantic_inputs.md`
- `COMMIT_MESSAGE_PHASE_01_4_1.md`
- `CHANGED_FILES_PHASE_01_4_1.md`
- `DEVELOPMENT_TEST_REPORT_PHASE_01_4_1.md`
