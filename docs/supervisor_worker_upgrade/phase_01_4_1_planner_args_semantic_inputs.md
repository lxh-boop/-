# Phase 01.4.1：Planner 参数合同与精确 Repair

## 本次解决的问题

真实请求 `分析600519` 时，MainAgent 已正确选择 W01、W02、W06，但把 `research_question`、`top_k`、`model_name` 等直接业务参数放入 `inputs`。严格语义输入 Schema 因此拒绝计划，Repair 又重复相同结构，Worker 未进入执行。

## 根因

公开 Worker 合同把直接任务参数 Schema 命名为 `input_schema`，而计划对象同时存在 `inputs` 字段。该命名容易让 LLM 稳定地把 `input_schema` 字段写入 `inputs`。

## 修改后合同

每个任务合同公开三类输入：

- `args_schema`：普通业务参数，只能写入任务 `args`；
- `semantic_inputs_schema`：上游 WorkerResult 引用，只能写入任务 `inputs`；
- `runtime_bound_args`：由程序写入 `args`，MainAgent 不得生成。

内部旧字段 `input_schema` 仅保留为代码兼容实现，不再出现在 MainAgent 能力目录中。

## 默认 TopK

`query_stock_prediction` 与 `query_latest_ranking` 的默认 `top_k` 为 `10`：

- 用户明确指定 TopK 时使用用户值；
- 用户未指定时由程序确定性补入 `args.top_k=10`；
- `model_name`、`trade_date` 未明确指定时不由 LLM 编造。

## 精确规划错误

在通用 JSON Schema 校验前增加字段归属预检。它不会替 MainAgent 修改计划，只会一次性报告：

- 哪些字段应从 `inputs` 移到 `args`；
- 哪些 runtime-bound 字段应删除并交由程序绑定；
- 哪些 `inputs` 角色不是合法 WorkerResult 引用。

真实失败候选现在会得到类似错误：

```text
planner_field_placement_error@$.tasks:
task=W01_001;move_to_args=research_question |
task=W02_001;move_to_args=model_name,top_k |
inputs_accept_only=from_task_id+expected_output_type
```

## Repair

`LLMService.generate_json()` 新增可选 `repair_guidance`。Planner 在唯一一次 Repair 中明确要求：

- `args_schema` 字段写入 `args`；
- `semantic_inputs_schema` 只写上游结果引用；
- `runtime_bound_args` 不生成；
- 默认 `top_k=10`；
- 不改变 Worker 节点、task_id、用户目标或已有语义边。

没有改变 timeout、模型绑定或 Repair 次数。

## 未修改

- MainAgent 仍直接选择 Worker 并生成完整 Worker DAG；
- Validator 仍只接受或拒绝；
- 程序不增加、删除、拆分、合并、替换或重连 Worker；
- `dependency_task_ids` 仍由 `inputs.from_task_id` 编译；
- `inputs` 严格 Schema 没有放宽；
- W02 内部数据查询和 typed payload 设计不变；
- 不修改 LLM timeout；
- 不执行 Git 写操作；
- 不重启前端，不执行 Docker build。

## 验收

- 77 项相关单元与消息系统测试通过；
- Phase 01 至 01.4.1 架构检查通过；
- Phase 01.1 至 01.4.1 验收通过；
- 真实失败候选可以生成精确字段归属错误；
- 修正计划中 W01、W02 并行，W06 依赖二者；
- W02 未显式提供 TopK 时最终 `args.top_k=10`；
- 未指定模型时不生成 `default_model`。
