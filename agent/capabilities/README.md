# Capability Contract / ContextBundle Runtime

当前主链（V23.0.16）：

```text
RequestBundle
→ GraphRef / ContextBinding
→ MainAgent
   1. Canonical Intent + Need + Need Requirement v2
   2. Worker Selection
→ Runtime deterministic Task Dependency compilation
→ WorkerAssignmentValidator / CapabilityPlanValidator
→ SpecialistRuntime
   ├─ Provider Worker 查询/生成成功后写入 ContextBundle
   ├─ Analysis / Decision Worker 按目标对象读取 ContextBundle
   └─ Worker 私有 Tool DAG 保持私有
→ WorkerResult / Task status
→ Need Completion
→ Request status
→ Forward Replan / final bundle report
```

## 1. 职责边界

- **Need**：MainAgent 本轮动态生成的业务目标，回答“这次必须完成什么”。
- **Need Requirement**：受控规划 IR，声明需要/产生的业务数据名称或必须由用户提供的参数。
- **Worker**：MainAgent 的专业能力选择单位。
- **CapabilityContract**：验证 Worker 本轮允许产生什么业务数据、需要哪些显式业务参数，以及是否允许 mutation。
- **ContextBundle**：当前 Run 唯一 Working Memory；保存本轮已成功获得的业务数据。
- **Tool**：Worker 私有执行单位；其局部 Tool DAG 与局部字段不作为跨 Worker 业务传输协议。

## 2. 业务数据：ContextBundle

跨 Worker 业务数据不再通过 RunSlotStore / SlotBinder 运输。

数据型 Worker 成功完成查询或生成后，由 Runtime 写入 ContextBundle：

```text
entity/object + data name + value
```

例如：

```text
600519 + evidence   + [...]
600519 + prediction + {...}
600519 + analysis   + {...}
user   + portfolio  + {...}
```

关键规则：

- 只有查询/生成成功后才写 data name。
- 成功查询得到空值时仍写入，例如 `evidence=[]`；因此“名称存在”表示本轮已完成该查询。
- Tool / Worker 失败时不写业务数据；失败由 WorkerResult / Task status 表达。
- 同一 Run 已存在相同实体/对象的相同 data name 时可以直接复用，不重复查询。
- 多实体场景仅补查缺失的实体/数据组合。

## 3. 分析与决策 Worker

W04 / W05 / W09 等分析或决策 Worker 不感知上游 Worker、Tool、Request 或跨 Worker Slot。

它们收到专业任务与相关 ContextBundle Working Memory 后：

1. 根据任务目标读取当前业务数据；
2. 自己判断数据质量与充分性；
3. 数据不足时只描述缺少什么业务信息；
4. 完成后把新的业务结果写回 ContextBundle。

W07 诊断的是 Runtime 状态，因此直接读取 Request / Task / WorkerResult / Run 状态，不走业务数据运输。

W06 最终报告在 Bundle-level 直接读取 verified Request result aggregate；不需要业务输入绑定。

## 4. 执行顺序与状态

执行流程不使用业务数据名称建立运输边。

```text
RequestItem.depends_on + Request.status
Task.dependency_task_ids + Task.status
WorkerResult.status / error
Run status + RunCheckpoint
```

这些已有状态数据负责：

- Ready / blocked 判断；
- Request 批次顺序；
- Worker 执行顺序；
- retry / replan / resume；
- waiting_user_input / waiting_context / failed / completed。

`TaskDependencyCompiler` 只编译执行阶段先后关系，不绑定业务数据。

## 5. 权限

Proposal 生成不是 mutation。

Runtime 使用 Worker 的明确权限控制能否修改业务状态：

```text
W04 risk analysis      can_mutate = false
W05 proposal/advice    can_mutate = false
W09 entity analysis    can_mutate = false
W08 graph-context write can_mutate = true
```

`effect_limit` 可以继续描述 Request 语义，但不能替代 mutation authorization。

## 6. Completion

完成状态仍分层：

```text
Tool Completion
→ Capability Completion
→ Need Completion
→ Request / Goal Completion
```

Capability Completion 验证的是 promised business-data names 是否已经由本轮 WorkerResult 物化。成功得到的空值也属于已物化业务结果。

Need Completion 按 Canonical Need 的 required output data names 判断，而不是按 Producer 身份或跨 Worker Slot 判断。

## 7. 保持不变的边界

- MainAgent 继续选择 Worker，不直接选择 Worker 私有 Tool。
- Worker 私有 Tool DAG 保持私有。
- GraphRef 仍是实体身份权威来源。
- RequestBundle 的 `depends_on` 继续负责跨 Request 顺序。
- Forward Replan 仍是异常/信息缺口恢复机制，不变成逐步 ReAct。
- BusinessParameterResolver 只处理真正必须由用户明确提供的参数。
- ContextBundle 是 Run 级工作记忆；跨 Run 数据新鲜度与长期记忆晋升不在 V23.0.16 自动处理范围内。
