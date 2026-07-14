# Phase 13：AgentMessage / CommunicationBus 通信系统完整执行指南

## 一、当前项目基础

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
```

现在进入：

```text
Phase 13：AgentMessage / CommunicationBus 通信系统
```

本阶段目标不是新增业务功能，而是把当前项目里的：

```text
dict 传参
临时 result
executor 内部状态
tool_result
approval plan
artifact ref
UI 状态
error/warning
```

统一为标准消息协议。

---

## 二、为什么要做通信系统

工具系统解决：

```text
能调用什么工具，工具怎么执行
```

上下文系统解决：

```text
每一步应该知道什么，哪些信息可见
```

通信系统解决：

```text
Agent、Planner、ToolExecutor、WriteGateway、Reporter、后续 ReAct/Reflection/Multi-Agent 之间怎么传递信息
```

最终目标是从：

```text
函数之间传 dict
executor 内部临时变量
页面直接读写结果
错误和工具结果格式不一致
```

升级为：

```text
AgentMessage
→ MessageEnvelope
→ MessageBus
→ MessageRouter
→ MessageStore
→ MessagePolicy
→ MessageTrace
```

---

## 三、总体架构

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
→ APPROVAL_REQUESTED / APPROVAL_RESULT_RECEIVED message
→ REPORT_DRAFTED message
→ FINAL_REPORT message
```

后续 Phase 15/16/17 会在此基础上做：

```text
ReAct Observe / Replan
Reflection Critic
Multi-Agent Handoff
```

所以本阶段要提前支持：

```text
ObservationMessage
HandoffMessage
ReflectionMessage
```

但本阶段不实现完整 ReAct、Reflection 和 Multi-Agent。

---

## 四、文档执行顺序

Codex 必须按以下顺序执行：

```text
1. 01_阶段A_通信链路审计与消息协议设计.md
2. 02_阶段B_AgentMessage核心模型_MessagePolicy_Sanitizer.md
3. 03_阶段C_MessageStore_MessageBus_MessageRouter.md
4. 04_阶段D_Executor_ToolExecutor_WriteGateway_Context接入.md
5. 05_阶段E_UI消息轨迹展示与真实网页功能检查.md
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

---

## 五、阶段边界

## 本阶段允许

1. 新增 AgentMessage 标准模型；
2. 新增 MessageEnvelope；
3. 新增 MessageType 枚举；
4. 新增 MessagePolicy；
5. 新增 MessageSanitizer；
6. 新增 MessageStore；
7. 新增 MessageBus；
8. 新增 MessageRouter；
9. 接入 Executor / ToolExecutor；
10. 接入 ContextManager；
11. 接入 WriteGateway / Approval；
12. 接入 Artifact ref；
13. 接入 UI 安全消息轨迹展示；
14. 增加测试；
15. 增加真实网页检查。

## 本阶段禁止

1. 不重写工具系统；
2. 不重写上下文系统；
3. 不实现完整 MemoryManager；
4. 不实现完整 ReAct；
5. 不实现完整 Reflection；
6. 不实现完整 Multi-Agent Handoff；
7. 不改变模拟盘核心算法；
8. 不改变审批 / revalidate / commit 边界；
9. 不让 MessageBus 直接写业务状态；
10. 不让 LLM 看到 secret；
11. 不让 UI 显示 raw confirmation_token；
12. 不删除旧 dict 调用；
13. 不一次性重构所有页面。

---

## 六、真实网页检查是强制要求

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
```

必须记录：

```text
WEB_CHECK_DONE = true
WEB_CHECK_METHOD = playwright / selenium / manual / health+manual
WEB_CHECK_PAGES = [...]
WEB_CHECK_RESULT = pass / fail
WEB_CHECK_ERRORS = [...]
```

如果没有真实网页检查，不允许写：

```text
NEXT_STAGE_ALLOWED = true
```

---

## 七、统一安全原则

Message 系统必须遵守：

```text
confirmation_token 原文不可进入 LLM message
confirmation_token 原文不可进入 UI message
API key 不可进入 LLM/UI message
DB path 不可进入 LLM/UI message
本地文件路径不进入 LLM/UI message
内部堆栈不进入 LLM/UI message
大对象只使用 summary + ref
Artifact path 不进入 LLM/UI message
WriteGateway 仍是唯一写确认入口
```

---

## 八、每阶段基础测试底线

每阶段至少运行：

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q
py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q
py -3 -m pytest tests/unit/test_phase12_context_core.py -q
py -3 -m pytest tests/unit/test_phase12_context_policy.py -q
py -3 -m pytest tests/unit/test_phase12_context_executor_integration.py -q
```

涉及写操作、审批或 UI 时，还必须运行：

```text
py -3 -m pytest tests/unit/test_agent_write_requires_confirmation.py -q
py -3 -m pytest tests/unit/test_agent_action_proposal_gateway.py -q
py -3 -m pytest tests/unit/test_multi_agent_phase3_human_approval.py -q
```

如果项目中已有 Phase 11 P1/P2 或 Phase 12 其它测试，也必须运行。

---

## 九、每阶段报告要求

每阶段必须生成：

```text
docs/phase13_<stage>_communication_report.md
```

报告必须包含：

```text
阶段目标
修改前状态表
新增/修改文件
消息类型
消息安全策略
MessageBus 接入点
ContextManager 接入点
ToolExecutor 接入点
WriteGateway 接入点
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

Phase 13 完成后必须满足：

1. AgentMessage 建立；
2. MessageEnvelope 建立；
3. MessageType 建立；
4. MessagePolicy 建立；
5. MessageSanitizer 建立；
6. MessageStore 建立；
7. MessageBus 建立；
8. MessageRouter 建立；
9. Executor 可以发布 USER_REQUEST / GOAL_PARSED / TASK_PLANNED / FINAL_REPORT；
10. ToolExecutor 可以发布 TOOL_CALL_REQUESTED / TOOL_RESULT_RECEIVED；
11. WriteGateway 可以发布 APPROVAL_REQUESTED / APPROVAL_RESULT；
12. ContextManager 可以把 context_id / artifact_refs / approval_refs 放入 message refs；
13. UI 可以安全展示消息轨迹摘要；
14. secret 不泄露；
15. 旧 dict 调用兼容；
16. 页面真实检查通过；
17. 全量测试通过；
18. 8501 health ok；
19. 输出最终通信系统交付报告。

---

## 十一、所有阶段完成后回复格式

只返回：

1. Phase 13 各阶段是否通过；
2. 新增通信系统模块；
3. 新增消息类型；
4. Executor / ToolExecutor / WriteGateway / ContextManager 接入点；
5. 安全过滤结果；
6. 真实网页检查结果；
7. 测试结果；
8. 仍保留的兼容入口；
9. 当前不做 MemoryManager / ReAct / Reflection / Multi-Agent 的说明；
10. 下一阶段建议。

不要粘贴完整代码。
