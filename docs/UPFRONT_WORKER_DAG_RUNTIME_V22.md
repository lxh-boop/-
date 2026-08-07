# V22.0.0 Upfront Worker DAG Runtime

## 目标

恢复并强化“先规划完整 Worker DAG，再执行 Worker；每个 Worker 再规划自己的私有 Tool DAG”的双层 DAG 模式。

正常执行不采用 Deep Agents 的 plan-as-you-go / 边执行边持续委派模式。仅保留适合当前项目的四个思想：

1. Worker `description` 驱动委派；
2. Worker 上下文隔离；
3. Worker 私有 Tool 不暴露给 MainAgent；
4. Worker 通过 RunSlotStore 发布干净结构化结果。

## 正常主链

```text
用户请求
→ MainEntryDecision（只判断 analysis / proposal / control 等运行边界）
→ GraphRef 解析
→ Canonical Intent Contract（唯一一次解释原始用户请求）
→ 一次性加载全部可用 Worker 的公开 description
→ Worker Call Selection（逐项覆盖 Intent Need）
→ 完整 Worker DAG
→ Runtime 通过 Slot 生产/消费关系推导 DAG 边
→ Worker 执行
   └─ 有私有 Tool 的 Worker：先生成完整 Tool DAG，再执行 Tool DAG
   └─ pure-LLM Worker（如 W09/W06）：直接消费绑定 Slot
→ RunSlotStore
→ 下游 Worker
→ W06 presentation-only
→ user_facing_report
→ 用户
```

## 单一语义权威

原始 `user_request` 只允许 `upfront_user_intent_planning` 阶段解释一次。

后续：

- Worker Call Selection 只读取 `canonical_intent_contract + worker_descriptions`；
- Worker DAG Planning 只读取 `canonical_intent_contract + selected_worker_calls + selected_worker_descriptions`；
- 正常路径禁止重新解释原始请求；
- Replan 仅用于实际失败恢复，并复用原来的 Canonical Intent Contract。

这样避免出现“入口解释说需要技术面，但后续规划又认为不需要内部信号”的语义漂移。

## Worker Description 与 Worker Call

MainAgent 在执行前一次性看到所有符合当前 effect limit 的 Worker 完整公开 description，但看不到：

- private Worker prompt；
- private Tool ID/details；
- Tool 参数；
- Tool 执行历史。

Worker Call 必须包含：

- `call_id`
- `worker_id`
- `objective`
- `covers_need_ids`
- `desired_output_slots`

Runtime 硬校验：

- 每个 required intent need 必须至少被一个 Worker Call 覆盖；
- Worker Call 请求的输出 Slot 必须是该 Worker 公共能力真实可产出的 Slot；
- Worker DAG 必须真正实现每个 Worker Call 的输出承诺；
- 未被选择的 Worker 不得偷偷进入 DAG。

## W09 → W06

W09 保持结构化分析 Worker：

- facts
- analysis
- uncertainties
- conclusion
- source_task_ids

W06 保持 presentation-only Worker：

- 输入：通过 SlotBinder 绑定的终端结构化 Slot；
- 输出：`user_facing_report` 和 `goal_completion_summary`；
- 不重新查询数据；
- 不新增业务事实或专业判断。

所有需要向用户交付自然语言业务结果的 Worker DAG，Runtime 都会加入一个 terminal presentation need。它不硬编码 W06；Worker Selection 根据公开输出能力选择能产出 `user_facing_report` 的 Worker。

若 Goal 要求 `user_facing_report` 但最终没有真正生成报告正文：

- Run 不得 `success=true`；
- 不得退化为拼接 W01/W09 等 Worker summary；
- 返回 `terminal_user_facing_report_missing`。

## Tool DAG

Worker Tool DAG 仍由 Worker 私有规划器负责。

这是第二层 DAG，并且在该 Worker 的 Tool 执行开始前一次性生成。正常路径不要求 MainAgent 逐个 Tool 介入。

已有 Tool 层失败重规划保留，仅作为异常恢复；已冻结且满足 required outputs 的 Tool 结果继续复用。

## 时间字段

本版本不改变通用 required-field 语义：字段/Slot 存在即可通过通用存在性检查。

诸如“最近 5 天”“最近一周”等时间约束由后续具体任务/Tool 注入，并由 Tool Result 返回真实 `publish_time / trade_date / as_of_time` 等时间信息。通用 Slot Validator 不承担业务新鲜度判断。
