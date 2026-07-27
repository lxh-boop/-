# 阶段 00：真实代码基线核对

## 1. 阶段目标

确认本机项目真实架构，纠正此前交接文档与本地代码不一致的问题。

## 2. 基线状态

- 项目目录：`D:\stock_daily_app`
- Git 分支：`codex/backend-agent-boundary-refactor`
- Git HEAD：`47be09c199190fc46446a1ff84911a626ec17c45`
- 已跟踪文件：1710
- 收集源码文件：1673
- 未跟踪源码文件：7
- 工作区：存在 Stage 6.6 未提交修改

## 3. 真实架构结论

当前代码已经具备：

```text
MainAgent / CoordinatorPlanner
  → 生成 GraphAgentTask Worker DAG
  → AgentCollaborationCoordinator._run_dag
  → ThreadPoolExecutor 并行执行 ready Worker
  → SpecialistRuntime 分派固定领域 Worker
  → 部分 Worker 调用 ToolExecutor 或确定性 Provider
```

当前代码尚不具备此前交接文档描述的：

- `agent/dag_validation.py`
- `agent/collaboration/capability_plan_validator.py`
- `agent/collaboration/dag_runtime.py`
- `agent/worker_planning/` 私有 Tool DAG 规划层

因此后续阶段必须按真实代码调整：

1. 先把当前 Worker DAG 接入 `agent_steps`；
2. 再把固定 Worker 执行器演进为私有 Tool DAG；
3. 之后增加强合同、滚动 Patch、受控并行和 Workflow-backed Worker。

## 4. 新增文件

无。

## 5. 修改文件

无。

## 6. 删除文件或目录

无。

## 7. 测试结果

基线收集器成功生成源码包和逐文件 SHA-256。此前强制要求不存在的 7 个文件导致收集失败，已将校验调整为警告并成功取得真实代码。
