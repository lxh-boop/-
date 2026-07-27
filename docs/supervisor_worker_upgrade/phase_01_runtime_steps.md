# 阶段 01：Worker DAG 运行记录接线

## 1. 阶段目标

将当前正式 `GraphAgentTask` Worker DAG 的创建、ready、running 和最终结果真实写入现有 `agent_steps`，使一次 Agent run 可以查询到 Worker 级执行轨迹。

## 2. 开始前状态

- 分支：`codex/backend-agent-boundary-refactor`
- 起始 commit：`47be09c199190fc46446a1ff84911a626ec17c45`
- 工作区：存在与本阶段无关的 Stage 6.6 未提交修改
- `agent_runs` 已由 `run_agent_request()` 创建
- 当前 `CoordinatorPlanner` 已生成 Worker DAG
- 当前 `_run_dag()` 已并行执行 Worker
- 当前正式链路没有调用 `create_step()`、`transition_step()` 或 `record_step_result()`

### 本阶段范围

- 运行时 Recorder 从正式入口传入协作层；
- Worker DAG 创建时注册 step；
- Worker ready/running/terminal 状态持久化；
- WorkerResult 摘要、状态、依赖、Agent、耗时、Artifact/Evidence 数量进入 step metadata；
- 增加针对当前正式协作层的单元测试和架构检查。

### 明确不修改

- Stage 6.6 前后端与设置文件；
- Planner 业务规则；
- Worker 划分；
- GraphRef；
- Tool 业务实现；
- Neo4j Schema；
- 数据库 Migration；
- API 外层响应合同。

## 3. 设计与实现决策

1. 复用现有 `AgentRuntimeRecorder`、`agent_steps` 和 `(run_id, step_id)` 联合主键。
2. 新增轻量 `CollaborationRuntimeServices`，只负责持久化，不向 LLM 暴露 Repository。
3. 正式入口复用同一个 Recorder，避免生成第二个 run_id。
4. `completed/partial/proposal_ready/waiting_approval` 映射为 step `succeeded`，原始 Worker 状态保存在 metadata。
5. `need_context/blocked/not_executed` 映射为 step `skipped`，避免把业务前提不满足误记为运行时崩溃。
6. `failed` 映射为 step `failed`。
7. 不新增数据库表和 Migration。

## 4. 新增文件

| 文件 | 用途 |
|---|---|
| `agent/collaboration/runtime_services.py` | Worker DAG 到 RuntimeRecorder 的适配层 |
| `tests/unit/test_supervisor_worker_phase_01_runtime_records.py` | Worker step 持久化、并行、身份一致性回归测试 |
| `scripts/refactor/check_supervisor_worker_phase_01.py` | 静态架构门禁 |
| `docs/supervisor_worker_upgrade/README.md` | 升级留存说明 |
| `docs/supervisor_worker_upgrade/phase_00_actual_baseline.md` | 真实基线核对 |
| `docs/supervisor_worker_upgrade/phase_01_runtime_steps.md` | 本阶段完整记录 |
| `docs/supervisor_worker_upgrade/upgrade_manifest.json` | 阶段总清单 |

## 5. 修改文件

| 文件 | 修改内容 |
|---|---|
| `agent/executor.py` | 将正式 `AgentRuntimeRecorder` 传入协作入口 |
| `agent/runtime.py` | 新增合法 step 状态转换，并允许结果 metadata 合并 |
| `agent/collaboration/integration.py` | 创建或复用 run-scoped RuntimeServices |
| `agent/collaboration/coordinator.py` | 注册 Worker task，记录 ready/running/terminal 生命周期 |

## 6. 删除文件或目录

无。

## 7. 实现的功能

- Worker 计划通过校验后立即写入 `agent_steps`；
- 依赖任务初始为 `pending`，无依赖任务初始为 `ready`；
- 调度前记录 `ready → running`；
- Worker 完成后记录最终状态、耗时和安全摘要；
- 并行 Worker 使用相同 run_id、不同 step_id，不互相覆盖；
- Runtime identity 不一致时明确拒绝；
- `graph_runtime.runtime_persistence.agent_steps_connected` 显示接线状态；
- 正式 API 返回结构保持兼容。

## 8. 数据库或合同变化

- 无新 Migration；
- 复用 `agent_steps`；
- 复用 `(run_id, step_id)` 联合主键；
- `GraphAgentTask` 与 `GraphWorkerResult` 公共合同未修改；
- 仅扩展 step metadata。

## 9. 测试过程

### 测试迭代 1：新增功能测试

- 命令：`pytest tests/unit/test_supervisor_worker_phase_01_runtime_records.py -q`
- 结果：5 passed
- 修改：无需修复，首次通过。

### 测试迭代 2：扩大到旧 collaboration_v2 测试

- 结果：收集失败。
- 原因：旧测试仍导入已删除的 `agent.collaboration_v2`，并读取已经删除的 Streamlit 文件。
- 处理：未删除、未跳过、未放宽断言；记录为基线遗留问题，不作为当前正式 `agent.collaboration` 阶段门禁。
- 日志：`development_logs/known_baseline_failure_01_obsolete_collaboration_v2.log`

### 测试迭代 3：旧统一运行时测试

- 结果：1 failed。
- 原因：测试未配置 LLM，正式硬切链路返回 `llm_service_not_configured`；测试仍期望旧 Tool runtime 成功结果。
- 处理：未伪造 LLM 或放宽测试；记录为基线测试与当前正式运行方式不一致。
- 日志：`development_logs/known_baseline_failure_02_unconfigured_llm.log`

### 测试迭代 4：当前正式链路阶段门禁

- 命令：
  `pytest tests/unit/test_supervisor_worker_phase_01_runtime_records.py tests/unit/test_agent_runtime_persistence.py tests/unit/test_agent_collaboration_current_workers.py tests/unit/test_worker_atomic_tool_runtime.py -q`
- 结果：23 passed
- 日志：`development_logs/test_03_phase_gate.log`

## 10. 最终测试结果

- Python 语法检查：通过
- 阶段架构检查：通过
- 新增测试：5 passed
- 当前 Runtime/Worker 相关回归：23 passed
- 旧 `collaboration_v2` 测试：基线遗留失败，未纳入正式门禁
- 旧未配置 LLM 端到端测试：基线遗留失败，未纳入正式门禁
- 完整仓库测试：不能声称全绿

## 11. Git 留存

- implementation_commit: 72b7809d6630bb0405155210b14ccc066fd99da3
- record_commit: 由安装器完成后写入 `D:\google\supervisor_worker_delivery\stage_records`
- branch: 安装时实际分支
- remote: `origin`
- push_result: PENDING

## 12. 验收标准核对

- [x] 每个当前 Worker task 可写入 `agent_steps`
- [x] 依赖关系可查询
- [x] Worker 生命周期可查询
- [x] 并行任务不覆盖
- [x] `run_id` 身份一致性校验
- [x] 不修改 Planner 与业务 Tool
- [x] 不创建同义表
- [x] 阶段门禁测试通过
- [ ] 本机安装、Git commit 和 push 由主 BAT 执行

## 13. 已知限制和遗留风险

1. 当前 Worker 内仍不是 LLM 生成的私有 Tool DAG；这是下一阶段任务。
2. ToolCall 到 `agent_tool_calls` 的统一接线尚未完成。
3. 旧 `collaboration_v2` 测试需要单独清理或迁移。
4. 真实 Neo4j + LLM 端到端测试需要可用测试配置。

## 14. 下一阶段输入

阶段 02 应基于当前固定 Worker 实现建立私有 Tool 计划合同和执行器，同时把正式 ToolExecutor 调用接入 `agent_tool_calls`。


## 15. 本机安装结果

- 安装时间：2026-07-27 19:39:02
- 分支：`codex/backend-agent-boundary-refactor`
- implementation commit：`72b7809d6630bb0405155210b14ccc066fd99da3`
- 阶段门禁：通过
- 语法日志：`D:\google\supervisor_worker_delivery\test_results\phase_01\20260727_193852\syntax_compileall.log`
- 架构日志：`D:\google\supervisor_worker_delivery\architecture_results\phase_01\20260727_193852\architecture_check.log`
- 测试日志：`D:\google\supervisor_worker_delivery\test_results\phase_01\20260727_193852\phase_gate_pytest.log`
- record commit 和 push 结果见 `D:\google\supervisor_worker_delivery\stage_records`。
