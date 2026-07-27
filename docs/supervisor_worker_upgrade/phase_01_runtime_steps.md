# 阶段 01：Worker DAG 运行记录接线

## 1. 阶段目标

将当前正式 Worker DAG 的创建、ready、running 和最终结果写入现有 `agent_steps`，使一次 Agent run 可以查询到 Worker 级执行轨迹。

## 2. 开始前状态

- 真实基线分支：`codex/backend-agent-boundary-refactor`；
- 初始基线提交：`47be09c199190fc46446a1ff84911a626ec17c45`；
- `agent_runs` 已由 `run_agent_request()` 创建；
- `CoordinatorPlanner` 已生成 Worker DAG；
- `_run_dag()` 已支持 Worker 批次并行；
- 正式协作链路原先没有写入 `agent_steps` 生命周期。

### 本阶段范围

- 正式 Recorder 从 Agent 入口传入协作层；
- Worker DAG 创建时注册 step；
- Worker ready、running 和 terminal 状态持久化；
- WorkerResult 摘要、依赖、Agent、耗时及引用数量进入 step metadata；
- 增加功能测试、数据库测试、回归测试和架构门禁。

### 明确不修改

- Planner 业务规则；
- Worker 划分；
- GraphRef；
- 业务 Tool；
- Neo4j Schema；
- API 外层响应合同；
- 真实交易逻辑。

## 3. 设计与实现决策

1. 复用 `AgentRuntimeRecorder`、`agent_steps` 和 `(run_id, step_id)` 联合主键；
2. 新增 `CollaborationRuntimeServices` 作为协作层持久化适配器；
3. 正式入口复用同一 Recorder，避免产生第二个 run_id；
4. `completed/partial/proposal_ready/waiting_approval` 映射为 `succeeded`；
5. `need_context/blocked/not_executed` 映射为 `skipped`；
6. `failed` 映射为 `failed`；
7. 原始 Worker 状态始终保存在 metadata；
8. 不新增数据库表和 Migration。

## 4. 新增文件

| 文件 | 用途 |
|---|---|
| `agent/collaboration/runtime_services.py` | Worker DAG 到 RuntimeRecorder 的适配层 |
| `tests/unit/test_supervisor_worker_phase_01_runtime_records.py` | Worker step 持久化、状态映射、并行和 run 隔离测试 |
| `scripts/refactor/check_supervisor_worker_phase_01.py` | 静态架构门禁 |
| `docs/supervisor_worker_upgrade/*` | 阶段设计、测试和留存记录 |

## 5. 修改文件

| 文件 | 修改内容 |
|---|---|
| `agent/executor.py` | 将正式 `AgentRuntimeRecorder` 传入协作入口 |
| `agent/runtime.py` | 增加合法 step 状态转换和结果 metadata 合并 |
| `agent/collaboration/integration.py` | 创建或复用 run-scoped RuntimeServices |
| `agent/collaboration/coordinator.py` | 注册 Worker task 并记录完整生命周期 |

## 6. 删除文件或目录

无。

## 7. 实现的功能

- Worker 计划通过校验后写入 `agent_steps`；
- 无依赖任务初始为 `ready`，有依赖任务初始为 `pending`；
- 调度时记录 `ready → running`；
- Worker 完成后记录终态、耗时和安全摘要；
- 并行 Worker 共用 run_id、使用不同 step_id；
- 同一 step_id 可在不同 run_id 中独立存在；
- Runtime identity 和 task run_id 不一致时明确拒绝；
- API 外层响应保持兼容。

## 8. 数据库或合同变化

- 无新 Migration；
- 复用 `agent_steps`；
- 复用 `(run_id, step_id)` 联合主键；
- `GraphAgentTask` 与 `GraphWorkerResult` 公共合同未改；
- 仅扩展 step metadata。

## 9. 自动测试层级

阶段安装器依次执行并分别保存日志：

1. 项目与交付 SHA-256 预检；
2. Python `py_compile`；
3. Python `compileall`；
4. 正式模块导入检查；
5. Supervisor–Worker 架构检查；
6. 阶段功能单元测试；
7. AgentRuntimeRecorder 数据库持久化测试；
8. 当前 Worker 协作回归测试；
9. Worker 原子 Tool Runtime 回归测试；
10. 相关测试组合门禁；
11. Git `diff --check`；
12. 交付文件敏感信息扫描；
13. 安装后最终 SHA-256 校验。

旧 `agent.collaboration_v2` 和未配置 LLM 的测试继续作为非阻断诊断记录，不删除、不跳过、不伪造通过。

## 10. 测试失败处理

- 若安装器本次替换或新增了文件，任何阻断门禁失败都会恢复备份；
- 若代码在运行安装器前已经是目标版本，安装器只做验证，测试失败不会回退用户已有代码；
- 回滚后再次校验恢复文件 SHA-256；
- 失败日志和 `rollback_result.json` 保留在 `D:\google\supervisor_worker_delivery`。

## 11. Git 留存策略

- 安装器不执行任何 Git 写操作；
- 不执行 `git add`、`git commit`、`git push`、`git reset`、`git restore` 或 `git stash`；
- 测试通过后生成 `git_status_after.txt`、`git_diff.patch`、`MANUAL_COMMIT_GUIDE.md`；
- 由用户手动审核和提交。

建议提交信息：

```text
feat(supervisor-runtime): persist worker dag lifecycle
```

## 12. 验收标准

- [x] 每个 Worker task 可写入 `agent_steps`；
- [x] 依赖关系可查询；
- [x] Worker 生命周期可查询；
- [x] 并行任务不覆盖；
- [x] 同 step_id 跨 run 隔离；
- [x] Worker 终态映射可验证；
- [x] 不修改 Planner 与业务 Tool；
- [x] 不创建同义运行表；
- [x] 安装器测试失败可回滚；
- [x] 安装器不自动提交 Git。

## 13. 已知限制

1. Worker 内仍是当前固定执行逻辑，尚未建设私有 Tool DAG；
2. ToolCall 到 `agent_tool_calls` 的统一接线尚未完成；
3. 旧 `collaboration_v2` 测试需要单独迁移；
4. 真实 Neo4j 与 LLM 端到端测试需要独立测试配置。

## 14. 下一阶段

阶段 02 补齐：

```text
agent_run
→ worker step
→ tool call
→ artifact / source
→ background task relation
```
