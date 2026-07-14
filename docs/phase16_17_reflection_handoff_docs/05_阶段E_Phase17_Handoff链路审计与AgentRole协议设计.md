# Phase 17-A：Handoff 链路审计与 AgentRole 协议设计

## 本阶段目标

进入 Phase 17，但本阶段先不要实现完整 Multi-Agent。重点是审计哪些任务需要转交，并设计 HandoffRequest / AgentRole / HandoffResult 协议。

目标：

```text
找出当前项目里哪些任务可拆给 specialist role
找出 CriticResult 何时需要 HANDOFF_REQUESTED
找出 ToolExecutor / Context / Message / Memory refs 如何传递给 specialist
设计 AgentRole / HandoffRequest / HandoffResult / HandoffPolicy / HandoffRouter
明确哪些角色只能读、哪些需要审批边界
```

---

## 一、允许做

1. 搜索和阅读代码；
2. 新增 Handoff 链路审计报告；
3. 设计 AgentRole；
4. 设计 HandoffRequest / HandoffResult；
5. 设计 HandoffPolicy / HandoffRouter；
6. 可以新增 `agent/handoff/README.md` 或设计草案；
7. 可以新增空包或类型草案，但不要接入主链。

---

## 二、禁止做

1. 不实现完整多 Agent 运行时；
2. 不让 specialist 直接写业务状态；
3. 不绕过 ToolExecutor / WriteGateway；
4. 不改调仓算法；
5. 不改 MemoryManager；
6. 不引入外部 Agent 框架；
7. 不新增异步队列；
8. 不改变 UI 行为。

---

## 三、必须检查的文件

```text
agent/executor.py
agent/goal_planning.py
agent/intent_decomposition/
agent/orchestration/multi_task_executor.py
agent/tool_engine.py
agent/tools/
agent/specialists/
agent/context/
agent/communication/
agent/reflection/
agent/react/
agent/memory/
app/pages/ai_agent.py
app/pages/system_monitor.py
```

---

## 四、必须输出 Handoff 链路审计表

生成：`docs/phase17_a_handoff_audit_report.md`

表格字段：handoff_source、file、function_or_class、current_task_type、candidate_agent_role、handoff_reason、required_context_refs、required_tool_names、requires_memory、requires_approval、contains_secret_risk、can_write_business_state、allowed_operation、blocked_operation、planned_handoff_phase。

至少覆盖：portfolio state 查询、risk analysis、portfolio proposal、stock/news/RAG evidence 查询、system status、report generation、critic blocking issue、critic handoff hint、approval-required proposal、multi_task_executor specialist-like outputs。

---

## 五、设计 AgentRole 协议

建议角色：

```text
COORDINATOR
PORTFOLIO_ANALYST
RISK_ANALYST
EVIDENCE_RETRIEVER
STRATEGY_GUARD
REPORT_WRITER
SYSTEM_DIAGNOSTIC
```

这些是受控角色，不是自由写状态的独立 Agent。每个角色只能通过 ToolExecutor 和 refs 工作。写操作必须由 COORDINATOR 生成 proposal，再走 WriteGateway。

---

## 六、设计 Handoff 协议

建议模型：HandoffRequest、HandoffResult、HandoffTrace、AgentRole、HandoffPolicy、HandoffRouter、HandoffCoordinator、SpecialistAdapter。

`HandoffRequest` 字段：handoff_id、conversation_id、run_id、task_id、source_role、target_role、reason、input_summary、context_refs、message_refs、observation_refs、replan_refs、critic_refs、memory_refs、artifact_refs、approval_refs、allowed_tools、blocked_tools、requires_approval、created_at、metadata。

`HandoffResult` 字段：handoff_id、run_id、task_id、target_role、status、summary、findings、recommended_action、artifact_refs、message_refs、observation_refs、critic_refs、approval_refs、errors、warnings、created_at、metadata。

---

## 七、真实网页基线检查

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

## 八、测试命令

```powershell
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py tests/unit/test_phase11_p0_write_gateway.py -q
py -3 -m pytest tests/unit/test_agent_write_requires_confirmation.py tests/unit/test_agent_action_proposal_gateway.py -q
py -3 -m pytest tests/unit/test_phase12_context_core.py tests/unit/test_phase12_context_policy.py tests/unit/test_phase12_context_executor_integration.py -q
py -3 -m pytest tests/unit/test_phase13_message_core.py tests/unit/test_phase13_message_store_bus.py tests/unit/test_phase13_message_policy.py -q
py -3 -m pytest tests/unit/test_phase14_memory_manager.py tests/unit/test_phase14_memory_tool_ui.py -q
py -3 -m pytest tests/unit/test_phase15_observation_core.py tests/unit/test_phase15_replan_policy.py tests/unit/test_phase15_agent_chat_loading.py -q
```

```powershell
py -3 -m pytest tests/unit/test_phase16_critic_core.py tests/unit/test_phase16_critic_policy.py tests/unit/test_phase16_critic_executor_integration.py -q
```

---

## 九、阶段报告

生成：`docs/phase17_a_handoff_audit_report.md`

必须包含：Handoff 链路审计表、AgentRole 设计、HandoffRequest/HandoffResult 字段设计、HandoffPolicy 设计、接入点设计、敏感字段风险识别、测试结果、网页检查结果、`NEXT_STAGE_ALLOWED = true / false`。

---

## 十、验收标准

1. 完成 Handoff 链路审计表；
2. 完成 AgentRole 与 Handoff 协议设计；
3. 完成接入点设计；
4. 未破坏现有代码；
5. compileall / 回归测试通过；
6. 真实网页检查通过；
7. NEXT_STAGE_ALLOWED = true。
