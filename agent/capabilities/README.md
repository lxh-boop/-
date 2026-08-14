# Capability Contract / Worker Runtime

当前主链（V23.0.10）：

```text
Request
→ MainEntryDecision + Typed Graph Focus
→ GraphRef Resolution Guard
→ MainAgent upfront planning
   1. Canonical Intent + Need + registered Need Requirements
   2. Worker Selection
   3. Compact Requirement Assignment
→ Deterministic CapabilityContract Expansion
→ WorkerAssignmentValidator / CapabilityPlanValidator
→ SlotBinder
→ SpecialistRuntime RequirementResolver
→ Worker 私有 Tool DAG
→ Slot 发布
→ Capability Completion
→ Need Completion
→ Forward Replan / waiting_user_input / final report
```

## 1. Need 与 CapabilityContract

- **Need**：MainAgent 本轮动态生成的业务目标，回答“这次必须完成什么”。
- **Need Requirement**：Need 的受控规划 IR，只能引用 `SemanticRequirementRegistry` 已注册语义，并区分 `input | output | parameter`。
- **Worker**：MainAgent 的选择单位，表示专业能力范围。
- **CapabilityContract**：由程序把 Need Requirement + Worker 静态能力 Schema 展开得到的本轮可验证合同。
- **Tool**：Worker 内部执行单位，只在 Worker 私有 Tool DAG 中可见。

## 2. V23.0.10 Need Requirement Compilation

第一段 Intent LLM 调用保持不变，但每个 business Need 必须声明受控 Requirement：

```text
Need
├─ input      完成本 Need 前必须具备的系统事实
├─ output     本 Need 真正应该产生的业务结果
└─ parameter  必须由用户明确决定、系统不得代替决定的值
```

关键规则：

- “你认为我的持仓应该怎么调整？”中的目标仓位属于 **output**，系统应生成 `reviewed_proposal / proposal.rebalance`；不能反向要求用户先给 `target_weight`。
- 只有用户明确指定配置规模，或任务明确要求在一个由用户决定的规模下做情景测算时，`target_allocation` 才是 **parameter**。
- LLM 不能自行发明 Slot、参数所有权、source policy、acceptance rule；这些由 Registry 静态维护。

## 3. Compact DAG IR

第三段 Planner LLM 调用次数不变，但不再重复输出完整 CapabilityContract。

LLM 只输出：

```text
task_requirements
├─ call_id
├─ requirement_ids
└─ additional_required_slots
```

程序根据 Registry 展开：

- `semantic_role`
- `source_policy`
- `satisfaction_rule`
- `accepted input/output patterns`
- `accepted business parameter patterns`
- `acceptance_rule_ids`
- Worker effect limit
- 完整 `CapabilityContract`

这样保留一次性完整规划，同时避免多 Worker 计划产生超长重复 JSON。

## 4. Typed Entity Focus

会话状态不再只有一个 `active_graph_refs`，同时按实体类型保留：

```text
typed_graph_focus:security
typed_graph_focus:portfolio
typed_graph_focus:event
```

因此：

```text
分析贵州茅台
→ last security = 600519

分析我的持仓
→ current scope = portfolio
→ last security 不删除

把刚刚那只股票加进去
→ reference_entity_type = security
→ 读取 typed_graph_focus:security
→ 恢复 600519
```

若请求明确需要历史 security，但没有任何权威 typed focus，则在 GraphRef 阶段返回 `unresolved_conversation_security`，禁止 Planner 使用“指定股票”继续猜。

## 5. Completion

完成状态分层：

```text
Tool Completion
→ Capability Completion
→ Need Completion
→ Goal Completion
```

Need Completion 按 Canonical Need 声明的 required output semantic 判断，而不是仅看 Worker 是否返回某个泛化结果。

## 6. 保持不变的边界

- MainAgent 继续选择 Worker，不直接选择私有 Capability/Tool。
- Planner 正常路径仍是 3 次 LLM 调用，不增加调用次数。
- Worker 私有 Tool DAG 保持私有。
- SlotBinder 只绑定/检测 Producer，不自动选择 Worker。
- Forward Replan 仍是异常恢复路径，不变成逐步 ReAct。
- RequirementResolver 继续严格区分：系统上下文缺失 / 用户参数缺失 / Tool 失败 / 业务为空 / 业务不足。
