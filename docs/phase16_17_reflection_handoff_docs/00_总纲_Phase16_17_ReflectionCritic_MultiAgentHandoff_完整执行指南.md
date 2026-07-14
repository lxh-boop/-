# Phase 16-17：Reflection Critic 与 Multi-Agent Handoff 完整执行指南

## 一、当前项目基础

当前项目已经完成：

```text
Phase 11：ToolExecutor / ToolDefinition / UnifiedToolResult / WriteGateway / approval / revalidate / commit
Phase 12：ContextManager / ContextBundle / ContextPolicy / ContextSanitizer / ContextStore
Phase 13：AgentMessage / MessageBus / MessageRouter / MessageTrace
Phase 14：MemoryManager / MemoryTool / Memory safe summary / MemoryStore health
Phase 15：ReAct Observe / Replan / AI Agent 长对话加载优化
```

Phase 15 已经完成：

```text
ObservationEvent / ObservePolicy / ObserveSanitizer / ObserveStore
ReActTrace / ReplanPolicy / ReplanLimiter
ToolExecutor / Executor / Context refs / MessageBus 接入 Observe + Replan
AI Agent 默认 10 条消息窗口 + 加载更早 + Context/Message/ReAct/Memory 懒加载
```

现在连续进入：

```text
Phase 16：Reflection Critic
Phase 17：Multi-Agent Handoff
```

---

## 二、总体目标

Phase 16 目标：

```text
给 Agent 增加运行时质检层。
基于 Observation / Replan / Message / Context / Memory refs 检查最终回答、工具结果、证据充分性、风险适配、审批边界和输出一致性。
Critic 只输出审查结果、修正建议、阻断原因和只读返工建议，不直接写业务状态。
```

Phase 17 目标：

```text
建立受控的多 Agent Handoff 能力。
Coordinator 根据用户目标、Critic 结果和任务需求，把任务转交给受控 Specialist Role。
Specialist 只能通过现有 ToolExecutor、Context refs、Message refs、Memory refs 工作，不能绕过 WriteGateway。
```

---

## 三、目标链路

```text
User Input
→ ContextManager
→ Planner / TaskPlan
→ ToolExecutor
→ ObservationEvent
→ ReplanDecision
→ Draft Answer / Proposal
→ ReflectionCritic
   → PASS：返回
   → REVISE_ANSWER：只改回答文本，不改业务结果
   → REPLAN_READONLY：只读返工，不写业务状态
   → ASK_USER：询问必要信息
   → REQUIRE_APPROVAL：必须走 WriteGateway
   → BLOCK_AND_REPORT：阻断并报告原因
   → HANDOFF_REQUESTED：进入 Phase 17 Handoff
→ HandoffCoordinator / Specialist Role
→ Final Report
```

---

## 四、文档执行顺序

Codex 必须按以下顺序执行：

```text
1. 01_阶段A_Phase16_Reflection链路审计与Critic协议设计.md
2. 02_阶段B_Phase16_Reflection核心模型_CriticPolicy_Sanitizer.md
3. 03_阶段C_Phase16_CriticEngine_Executor接入_只读审查.md
4. 04_阶段D_Phase16_Reflection_UI展示与真实网页检查.md
5. 05_阶段E_Phase17_Handoff链路审计与AgentRole协议设计.md
6. 06_阶段F_Phase17_Handoff核心模型_Router_Policy_Sanitizer.md
7. 07_阶段G_Phase17_Coordinator_SpecialistHandoff_运行时接入.md
8. 08_阶段H_Phase16_17_最终收敛_覆盖率_回归_交付报告.md
```

每个阶段必须：

```text
先阅读阶段文档
→ 输出本阶段目标、禁止事项、检查文件、预计新增/修改文件、测试命令、网页检查计划
→ 检查当前代码
→ 修改代码
→ 运行 compileall
→ 运行 pytest
→ 启动/检查 8501
→ 真实打开网页检查功能
→ 写阶段报告
→ 报告写 NEXT_STAGE_ALLOWED = true
→ 才能进入下一阶段
```

失败时：立即停止，不得进入下一阶段，报告写 `NEXT_STAGE_ALLOWED = false`。

---

## 五、阶段边界

## 允许做

1. 新增 `agent/reflection/`；
2. 新增 CriticResult / CriticIssue / CriticPolicy / CriticSanitizer / CriticEngine；
3. 将 Critic 以只读审查方式接入 Executor 最终输出链路；
4. 新增 `agent/handoff/`；
5. 新增 HandoffRequest / HandoffResult / AgentRole / HandoffPolicy / HandoffRouter / HandoffCoordinator；
6. 将 Handoff 以受控方式接入 Executor / Context refs / MessageBus / UI；
7. 增加测试和真实网页检查；
8. 保留旧接口兼容。

## 禁止做

1. 不训练模型，不做强化学习，不做微调；
2. 不让 Critic / Handoff / Specialist 直接写模拟盘、策略、资金、持仓；
3. 不绕过 WriteGateway / approval / revalidate / commit；
4. 不重写 ToolExecutor / ContextManager / MessageBus / MemoryManager；
5. 不引入外部 Agent 框架，不引入 Celery / Redis / Kafka；
6. 不改调仓算法和组合规则；
7. 不暴露 confirmation_token、API key、Tushare token、数据库路径、本地路径、内部堆栈、raw payload；
8. 不把私有链式思考写入日志或 UI，只能保存 operational summary；
9. 不破坏 Phase 15 长对话加载优化。

---

## 六、统一安全原则

```text
Critic 只能审查和建议，不能执行。
Handoff 只能转交和汇总，不能写业务状态。
Specialist 只能通过 ToolExecutor 和 refs 工作。
所有写操作仍必须走 WriteGateway。
所有大对象只保留 summary + refs。
所有 UI/LLM 可见内容必须经过 sanitizer。
```

---

## 七、每阶段基础测试底线

```powershell
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py tests/unit/test_phase11_p0_write_gateway.py -q
py -3 -m pytest tests/unit/test_agent_write_requires_confirmation.py tests/unit/test_agent_action_proposal_gateway.py -q
py -3 -m pytest tests/unit/test_phase12_context_core.py tests/unit/test_phase12_context_policy.py tests/unit/test_phase12_context_executor_integration.py -q
py -3 -m pytest tests/unit/test_phase13_message_core.py tests/unit/test_phase13_message_store_bus.py tests/unit/test_phase13_message_policy.py -q
py -3 -m pytest tests/unit/test_phase14_memory_manager.py tests/unit/test_phase14_memory_tool_ui.py -q
py -3 -m pytest tests/unit/test_phase15_observation_core.py tests/unit/test_phase15_replan_policy.py tests/unit/test_phase15_agent_chat_loading.py -q
```

---

## 八、真实网页检查是强制要求

```text
http://127.0.0.1:8501/_stcore/health
首页 / 预测排名
AI Agent 页面
AI 模拟盘页面
系统监控页面
报告页面，如存在
```

AI Agent 至少真实输入：

```text
查看我的当前持仓
分析当前组合风险
给我一个调仓建议
查看最新报告
查看系统状态
我上次为什么建议调仓？
```

必须记录：

```text
WEB_CHECK_DONE = true
WEB_CHECK_METHOD = health + Streamlit AppTest + Playwright/浏览器真实渲染或明确降级说明
WEB_CHECK_PAGES = [...]
WEB_CHECK_RESULT = PASS / FAIL
WEB_CHECK_ERRORS = []
```

如果没有真实网页检查，不允许写 `NEXT_STAGE_ALLOWED = true`。

---

## 九、每阶段报告要求

每阶段必须生成对应报告：

```text
docs/phase16_<stage>_reflection_report.md
或
docs/phase17_<stage>_handoff_report.md
```

报告必须包含：

```text
阶段目标
修改前状态表
新增/修改文件
核心模型 / 策略 / 接入点
安全边界说明
兼容旧接口说明
测试命令与结果
真实网页检查方法
真实网页检查页面
真实网页检查结果
失败项
未完成项
NEXT_STAGE_ALLOWED = true / false
```

---

## 十、最终完成标准

1. CriticResult / CriticIssue / CriticPolicy / CriticSanitizer / CriticEngine 完成；
2. Critic 可输出 PASS / REVISE_ANSWER / REPLAN_READONLY / ASK_USER / REQUIRE_APPROVAL / BLOCK_AND_REPORT / HANDOFF_REQUESTED；
3. Critic 不直接提交任何写操作；
4. HandoffRequest / HandoffResult / AgentRole / HandoffPolicy / HandoffRouter / HandoffCoordinator 完成；
5. Specialist Role 只能通过现有 ToolExecutor 和 refs 工作；
6. Handoff 不绕过 WriteGateway；
7. MessageBus 可以记录 REFLECTION_* 和 HANDOFF_* 消息；
8. AI Agent 页面可以安全展示 Critic/Handoff 摘要；
9. 系统监控页面可以展示 Reflection/Handoff health；
10. secret 不泄露；
11. 页面真实检查通过；
12. 全量测试通过；
13. 8501 health ok；
14. 输出最终交付报告。

---

## 十一、所有阶段完成后回复格式

只返回：

1. Phase 16-17 各阶段是否通过；
2. 新增 reflection 模块；
3. 新增 handoff 模块；
4. 新增消息类型；
5. Executor / ToolExecutor / Context / Message / UI 接入点；
6. Critic 决策类型；
7. Handoff 角色与路由规则；
8. 安全过滤结果；
9. 真实网页检查结果；
10. 测试结果；
11. 兼容入口；
12. 未完成项；
13. 下一阶段建议。

不要粘贴完整代码。
