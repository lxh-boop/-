# Phase 15：ReAct Observe / Replan 完整执行指南

## 一、本次修改主要内容简述

Phase 15 的主线是建立 ReAct Observe / Replan 能力：让 Agent 在工具调用、上下文构建、任务执行、审批预览和最终回答过程中，能够把关键结果转成标准 Observation，并在失败、信息不足、权限受限、工具返回异常、证据不足、任务结果不满足目标时，触发受控的 Replan。

同时，本阶段必须修复当前 AI Agent 对话页面在消息超过约 7 条后加载明显变慢的问题。加载优化不是独立阶段，而是 Phase 15 的性能优化子任务，必须和 ReAct trace / observation / memory safe summary 一起设计，避免页面每次刷新都全量加载历史消息、工具轨迹、证据详情、Memory records 和开发者详情。

## 二、当前项目基础

当前项目已经完成：

```text
Phase 11：工具系统重构
- ToolDefinition
- ToolAdapter
- ToolExecutor
- UnifiedToolResult
- DomainService
- CapabilityIndex
- Artifact / audit
- Write Gateway / approval / revalidate / commit

Phase 12：上下文系统重构
- ContextManager
- ContextBundle
- ContextPolicy
- ContextSanitizer
- ContextWindow
- ContextStore
- ContextResolver
- UserContext / ConversationContext / TaskContext / ToolContext
- ArtifactContext / ApprovalContext / RuntimeContext

Phase 13：AgentMessage / CommunicationBus 通信系统
- AgentMessage
- MessageEnvelope
- MessageType
- MessagePolicy
- MessageSanitizer
- MessageWindow
- MessageStore
- MessageBus
- MessageRouter
- MessageTrace
- Executor / ToolExecutor / WriteGateway / ContextManager 接入
- UI safe message trace

Phase 14：MemoryManager 记忆系统
- MemoryRecord / MemoryType / MemoryPolicy / MemorySanitizer
- WorkingMemory
- SQLiteMemoryStore
- MemoryRetriever
- MemoryManager
- MemoryCandidateExtractor / Consolidator / Pruner
- MemoryTool readonly
- Context / Message / Tool / AI Agent UI / System Monitor 接入
```

现在进入：

```text
Phase 15：ReAct Observe / Replan
```

后续阶段：

```text
Phase 16：Reflection Critic
Phase 17：Multi-Agent Handoff
```

## 三、为什么要做 ReAct Observe / Replan

工具系统解决：

```text
能调用什么工具，工具怎么执行，执行结果如何统一
```

上下文系统解决：

```text
每一步应该知道什么，哪些信息可见，如何裁剪上下文
```

通信系统解决：

```text
Agent、Planner、ToolExecutor、WriteGateway、Reporter 之间如何传递标准消息
```

记忆系统解决：

```text
哪些安全摘要、用户偏好、证据、组合事件可以被短期或长期保存、检索、展示
```

ReAct Observe / Replan 解决：

```text
工具结果和执行状态如何被观察、判断、反馈给任务计划，并在必要时重新规划
```

目标链路：

```text
User Input
→ USER_REQUEST message
→ ContextManager
→ CONTEXT_CREATED message
→ GOAL_PARSED message
→ TASK_PLANNED message
→ TOOL_CALL_REQUESTED message
→ ToolExecutor
→ TOOL_RESULT_RECEIVED message
→ OBSERVATION_CREATED message
→ ObservePolicy 判断
→ REPLAN_REQUESTED / REPLAN_SKIPPED / REPLAN_APPLIED
→ 新 TaskPlan 或局部任务修正
→ REPORT_DRAFTED message
→ FINAL_REPORT message
```

## 四、阶段执行顺序

Codex 必须按以下顺序执行：

```text
1. 01_阶段A_ReAct链路审计与加载性能基线.md
2. 02_阶段B_Observation核心模型_ObservePolicy_Sanitizer.md
3. 03_阶段C_ObserveStore_ReActTrace_ReplanPolicy.md
4. 04_阶段D_Executor_ToolExecutor_Context接入Observe_Replan.md
5. 05_阶段E_AI_Agent_UI加载优化与Memory视图轻量加载.md
6. 06_阶段F_最终收敛_覆盖率_回归_交付报告.md
```

每个阶段必须：

```text
先阅读阶段文档
→ 输出本阶段范围、禁止事项、检查文件、测试命令、网页检查计划
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

如果失败：

```text
立即停止
不得进入下一阶段
报告写 NEXT_STAGE_ALLOWED = false
```

## 五、本阶段允许

1. 新增 ObservationEvent 标准模型；
2. 新增 ObservationType / ObservationStatus / ObservationSeverity；
3. 新增 ObservePolicy；
4. 新增 ObserveSanitizer；
5. 新增 ReActTrace / ReActStep；
6. 新增 ObserveStore；
7. 新增 ReplanPolicy；
8. 新增 ReplanDecision / ReplanReason / ReplanScope；
9. 接入 ToolExecutor 的工具结果观察；
10. 接入 Executor 的任务执行观察；
11. 接入 ContextManager 的 context refs；
12. 接入 MessageBus 的 OBSERVATION_CREATED / REPLAN_* 消息；
13. 接入 MemoryTool readonly summary，但只做安全摘要和 refs；
14. 优化 AI Agent 页面加载速度；
15. 优化 Memory 视图轻量加载；
16. 增加测试；
17. 增加真实网页检查。

## 六、本阶段禁止

1. 不实现完整 Reflection Critic；
2. 不实现完整 Multi-Agent Handoff；
3. 不重写工具系统；
4. 不重写上下文系统；
5. 不重写 MemoryManager；
6. 不改变模拟盘核心算法；
7. 不改变审批 / revalidate / commit 边界；
8. 不让 Replan 绕过 WriteGateway；
9. 不让 ObserveStore 直接写业务状态；
10. 不让 MemoryTool 从 readonly 变成 write；
11. 不让 LLM 看到 secret；
12. 不让 UI 显示 raw confirmation_token；
13. 不删除旧 dict 调用；
14. 不一次性重构所有页面；
15. 不因为加载优化删除功能；
16. 不把完整 Memory records 全量注入 prompt；
17. 不把完整历史对话全量注入 prompt；
18. 不默认展开工具轨迹、证据详情、developer details。

## 七、真实网页检查是强制要求

每个阶段都必须真实检查网页，不允许只跑 pytest。

必须检查：

```text
http://127.0.0.1:8501/_stcore/health
首页 / 预测排名
AI Agent 页面
AI 模拟盘页面
系统监控页面
报告页面，如存在
```

AI Agent 页面至少真实输入：

```text
查看我的当前持仓
分析当前组合风险
给我一个调仓建议
查看系统状态
我上次为什么建议调仓？
```

加载优化阶段还必须构造长对话检查：

```text
连续输入不少于 12 条 AI Agent 消息
刷新页面
切换页面后返回 AI Agent
打开/关闭 message trace 折叠区
打开/关闭 tool details 折叠区
打开/关闭 memory summary 折叠区
```

必须记录：

```text
WEB_CHECK_DONE = true
WEB_CHECK_METHOD = playwright / selenium / manual / health+manual / Streamlit AppTest
WEB_CHECK_PAGES = [...]
WEB_CHECK_RESULT = pass / fail
WEB_CHECK_ERRORS = [...]
```

如果没有真实网页检查，不允许写：

```text
NEXT_STAGE_ALLOWED = true
```

## 八、统一安全原则

ReAct / Observe / Replan 必须遵守：

```text
confirmation_token 原文不可进入 LLM message
confirmation_token 原文不可进入 UI message
API key 不可进入 LLM/UI message
Tushare token 不可进入 LLM/UI message
DB path 不可进入 LLM/UI message
本地文件路径不进入 LLM/UI message
内部堆栈不进入 LLM/UI message
raw_positions 不进入 LLM/UI message
raw_evidence 不进入 LLM/UI message
raw_tool_payload 不进入 LLM/UI message
大对象只使用 summary + ref
Artifact path 不进入 LLM/UI message
MemoryTool 只读
WriteGateway 仍是唯一写确认入口
Replan 不得直接 commit
```

## 九、加载优化原则

AI Agent 页面必须从“全量加载”改为“窗口加载 + 分页 + 懒加载 + 缓存 + 安全摘要”。

要求：

```text
默认只渲染最近消息窗口，例如最近 8~10 条
历史消息通过“加载更早消息”分页获取
message trace 默认只显示 summary
tool result / evidence details 默认折叠，展开时再读取
developer details 默认折叠，展开时再渲染
Memory 默认只展示 safe summary，不全量展示 memory_records
Context 注入只保留必要 memory refs 和 observation refs
稳定查询允许短 TTL cache
session_state 只保存 UI 状态和分页游标，不保存敏感大对象
```

禁止：

```text
每次 Streamlit rerun 全量查询所有历史消息
每次进入 AI Agent 页面全量渲染所有 message trace
每次进入 AI Agent 页面全量读取所有 memory records
每次输入后重建所有历史 UI 卡片
把 raw tool payload 放进 session_state
把 full memory records 放进 prompt
```

## 十、每阶段基础测试底线

每阶段至少运行：

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q
py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q
py -3 -m pytest tests/unit/test_phase12_context_core.py -q
py -3 -m pytest tests/unit/test_phase12_context_policy.py -q
py -3 -m pytest tests/unit/test_phase12_context_executor_integration.py -q
py -3 -m pytest tests/unit/test_phase13_message_core.py -q
py -3 -m pytest tests/unit/test_phase13_message_store_bus.py -q
py -3 -m pytest tests/unit/test_phase14_memory_manager.py -q
py -3 -m pytest tests/unit/test_phase14_memory_tool_ui.py -q
```

涉及写操作、审批或 UI 时，还必须运行：

```text
py -3 -m pytest tests/unit/test_agent_write_requires_confirmation.py -q
py -3 -m pytest tests/unit/test_agent_action_proposal_gateway.py -q
py -3 -m pytest tests/unit/test_multi_agent_phase3_human_approval.py -q
```

如果项目中已有 Phase 11/12/13/14 其它测试，也必须运行。

## 十一、每阶段报告要求

每阶段必须生成：

```text
docs/phase15_<stage>_react_observe_replan_report.md
```

报告必须包含：

```text
阶段目标
修改前状态表
新增/修改文件
Observation 类型
ObservePolicy 规则
ReplanPolicy 规则
MessageBus 接入点
ContextManager 接入点
ToolExecutor 接入点
WriteGateway 边界说明
MemoryTool readonly 边界说明
AI Agent 加载优化结果，如本阶段涉及
兼容旧接口说明
测试命令与结果
真实网页检查方法
真实网页检查页面
真实网页检查结果
失败项
未完成项
NEXT_STAGE_ALLOWED = true / false
```

## 十二、核心验收标准

Phase 15 完成后必须满足：

1. ObservationEvent 建立；
2. ObservationType 建立；
3. ObservePolicy 建立；
4. ObserveSanitizer 建立；
5. ObserveStore 建立；
6. ReActTrace 建立；
7. ReplanPolicy 建立；
8. ReplanDecision 建立；
9. ToolExecutor 可以从工具结果生成 observation；
10. Executor 可以根据 observation 触发受控 replan；
11. Replan 不绕过 WriteGateway；
12. Replan 有最大次数限制，不能无限循环；
13. MessageBus 能记录 OBSERVATION_CREATED / REPLAN_REQUESTED / REPLAN_APPLIED / REPLAN_SKIPPED；
14. ContextManager 只接收 observation refs / memory refs，不接收 raw payload；
15. MemoryTool 仍然 readonly；
16. AI Agent 页面默认只加载最近消息窗口；
17. 历史消息支持分页加载；
18. 工具轨迹和证据详情支持懒加载；
19. Memory 视图只默认展示 safe summary；
20. 长对话超过 12 条后页面仍可正常输入、切换和刷新；
21. confirmation_token 不进 message；
22. confirmation_token 不进 UI；
23. secret 不泄露；
24. 大对象摘要 + ref；
25. 旧接口兼容；
26. 页面真实检查通过；
27. 全量测试通过；
28. 8501 health ok；
29. 输出最终 Phase 15 交付报告。

## 十三、所有阶段完成后回复格式

只返回：

1. Phase 15 各阶段是否通过；
2. 新增 ReAct / Observe / Replan 模块；
3. 新增 Observation 类型；
4. 新增 Replan 类型；
5. Executor / ToolExecutor / MessageBus / ContextManager 接入点；
6. AI Agent 加载优化结果；
7. Memory 视图轻量加载结果；
8. 安全过滤结果；
9. 真实网页检查结果；
10. 测试结果；
11. 仍保留的兼容入口；
12. 当前不做 Reflection Critic / Multi-Agent Handoff 的说明；
13. 下一阶段建议。

不要粘贴完整代码。
