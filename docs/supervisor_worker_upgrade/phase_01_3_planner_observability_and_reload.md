# Supervisor–Worker 阶段 01.3：语义输入编排、依赖编译与 Planner 可观测性

## 1. 本阶段解决的问题

阶段 01.2 的真实运行中，MainAgent 同时生成了：

- `args.related_task_ids`
- `dependency_task_ids`

两份字段都表达了上游任务关系，但模型输出不一致，导致 Validator 拒绝整张 Worker DAG。

本阶段将职责调整为：

```text
MainAgent 生成语义输入 inputs
→ 程序只从 inputs[*].from_task_id 确定性推导 dependency_task_ids
→ Validator 校验引用、输出类型、环和报告可达性
→ 执行原始语义计划对应的编译后 DAG
```

程序不会推测或新增 MainAgent 未声明的依赖边。

## 2. MainAgent 输出合同

MainAgent 不再输出 `dependency_task_ids`，也不再把任务 ID 放入 `args`。

```json
{
  "task_id": "W06_001",
  "worker_id": "W06",
  "task_type": "write_report",
  "objective": "依据上游研究结果形成最终报告",
  "args": {
    "report_goal": "形成用户可读的分析报告",
    "reply_language": "zh"
  },
  "inputs": {
    "upstream_results": {
      "from_task_id": "W01_001",
      "expected_output_type": "EntityResearchResult"
    }
  },
  "constraints": ["upstream_results_only"],
  "expected_output_type": "FinalReport",
  "priority": 2
}
```

单个输入引用可以写对象，多个引用写数组。运行时统一标准化为数组。

## 3. 程序编译结果

编译器只读取 MainAgent 已声明的 `from_task_id`：

```json
{
  "inputs": {
    "upstream_results": [
      {
        "from_task_id": "W01_001",
        "expected_output_type": "EntityResearchResult"
      }
    ]
  },
  "dependency_task_ids": ["W01_001"]
}
```

该过程属于结构化编译，不是 Validator 自动修改业务 DAG：

- 不选择 Worker；
- 不新增 Worker；
- 不删除 Worker；
- 不拆分或合并节点；
- 不推测额外依赖；
- 不改变 `from_task_id`；
- 只把显式语义引用转换为执行器需要的依赖列表。

## 4. Worker 能力卡

Worker 能力卡新增 `upstream_input_bindings`，用于声明：

- 允许的输入角色名；
- 每个角色接受的上游输出类型；
- 是否必需；
- 最少和最多引用数量。

示例：W03 图影响分析 Worker：

```json
{
  "source_analysis": {
    "accepted_output_types": ["EntityResearchResult"],
    "required": true
  },
  "target_state": {
    "accepted_output_types": ["PortfolioAnalysisResult"],
    "required": true
  }
}
```

旧的 `dependency_arg_fields` 不再暴露给 MainAgent，也不参与规划。

## 5. Validator 校验范围

Validator 只接受或拒绝，不修改语义计划。校验包括：

- Worker 和 task_type 是否匹配；
- `args` 是否符合普通业务参数 Schema；
- `args` 是否错误包含任务 ID；
- `inputs` 角色是否由 Worker 声明；
- `from_task_id` 是否存在；
- 是否存在自依赖；
- `expected_output_type` 是否与上游真实输出一致；
- 输入数量是否满足 Worker 合同；
- 编译后的 DAG 是否有环；
- 所有专业任务是否可达 FinalReport。

## 6. Worker Runtime 接入

`GraphAgentTask` 升级为 `graph_agent_task.v2`，新增：

```text
inputs
input_task_ids(role)
```

W03、W04、W06 已改为从语义角色读取上游任务：

```text
W03: source_analysis / target_state
W04: portfolio_state / related_analysis
W06: upstream_results
```

运行记录同时保存：

- semantic_inputs；
- dependency_task_ids；
- dependency_derivation=`compiled_from_semantic_inputs`。

## 7. Planner 实时事件

保留并增强阶段 01.3 可观测性：

```text
GRAPH_REF_RESOLUTION_STARTED
GRAPH_REF_RESOLUTION_COMPLETED
WORKER_PLANNING_STARTED
LOCAL_LLM_REQUEST_STARTED
LOCAL_LLM_RESPONSE_RECEIVED
WORKER_PLAN_CANDIDATE_GENERATED
WORKER_PLAN_VALIDATION_FAILED
WORKER_PLAN_REPAIR_STARTED
WORKER_PLAN_REPAIR_FAILED
WORKER_PLAN_DEPENDENCIES_DERIVED
WORKER_DAG_VALIDATED
RUN_FAILED / RUN_COMPLETED
```

失败候选计划以脱敏、只读诊断快照保存，不会执行。

## 8. 其他修复

- MainAgent 规划错误不再误报为 Neo4j 不可用；
- Markdown 文件名包含 Run ID，避免同名问题覆盖；
- Uvicorn reload 只监听源码目录，不监听 `runtime`、`outputs`、`data`、`models`；
- 不修改本地 LLM timeout、模型配置和重试次数。

## 9. 验收标准

1. MainAgent 输出中不存在 `dependency_task_ids`。
2. MainAgent 的任务 ID 引用只出现在 `inputs`。
3. 程序推导的依赖列表与 `inputs[*].from_task_id` 一致。
4. 程序不能生成任何未声明的依赖边。
5. 错误输入角色、错误输出类型、自依赖和环均被拒绝。
6. W01 → W06 的简单分析计划可编译为 W06 依赖 W01。
7. 所有阶段 01～01.3 回归测试通过。
