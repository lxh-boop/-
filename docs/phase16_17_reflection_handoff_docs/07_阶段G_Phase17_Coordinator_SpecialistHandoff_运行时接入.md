# Phase 17-C：Coordinator、Specialist Handoff 与运行时接入

## 本阶段目标

把 Multi-Agent Handoff 以受控方式接入运行时：Coordinator 根据任务、Critic 结果和上下文，把任务转交给 Specialist Role；Specialist 通过现有 ToolExecutor 和 refs 工作，不直接写业务状态。

目标：新增 HandoffCoordinator / SpecialistAdapter；Executor 可在 CriticAction.HANDOFF_REQUESTED 或复杂任务时触发 Handoff；MessageBus 发布 HANDOFF_*；Context 只携带 handoff refs；UI 可看到安全 handoff summary。

---

## 一、允许做

1. 新增 `agent/handoff/handoff_coordinator.py`；
2. 新增 `agent/handoff/specialist_adapter.py`；
3. 最小修改 `agent/executor.py`、Context types/policy、MessageType；
4. 小范围修改 AI Agent UI 和系统监控；
5. 增加集成测试和网页检查。

---

## 二、禁止做

1. 不让 Specialist 直接调用 commit；
2. 不让 Specialist 直接改持仓、策略、资金；
3. 不绕过 WriteGateway；
4. 不重写 ToolExecutor / Planner；
5. 不引入外部 Agent 框架或后台队列；
6. 不让多个 Agent 无限循环；
7. 不破坏 Phase 15 长对话加载优化；
8. 不破坏 Phase 16 Critic 审查。

---

## 三、建议新增/修改文件

```text
agent/handoff/handoff_coordinator.py
agent/handoff/specialist_adapter.py
agent/handoff/__init__.py
agent/executor.py
agent/context/context_types.py
agent/context/context_policy.py
agent/communication/message_types.py
app/pages/ai_agent.py
app/pages/system_monitor.py
tests/unit/test_phase17_handoff_coordinator.py
tests/unit/test_phase17_handoff_executor_integration.py
tests/unit/test_phase17_handoff_ui_safe_summary.py
```

---

## 四、HandoffCoordinator

必须支持：plan_handoff()、execute_handoff()、merge_handoff_results()、stop_on_blocking_result()、limit_handoff_depth()。

限制：max_handoff_depth 默认 2；max_specialists_per_run 默认 3；same role repeat 默认 1；所有 specialist 返回 summary + refs。

---

## 五、SpecialistAdapter

Specialist 不是自由 Agent，而是受控 adapter。必须支持 run_portfolio_analyst()、run_risk_analyst()、run_evidence_retriever()、run_strategy_guard()、run_report_writer()、run_system_diagnostic()。每个 specialist 只能调用 HandoffPolicy 允许的工具，输出必须是 HandoffResult。

---

## 六、Executor 接入

触发条件：CriticAction.HANDOFF_REQUESTED；用户问题明显需要多个专业角色；调仓建议需要 portfolio + risk + strategy guard；证据不足需要 evidence retriever；系统问题需要 system diagnostic。

流程：Coordinator 生成 HandoffRequest -> MessageBus 发布 HANDOFF_REQUESTED -> SpecialistAdapter 执行只读任务 -> MessageBus 发布 HANDOFF_RESULT -> Coordinator 汇总 -> Critic 可再次审查最终汇总 -> 最终返回用户。

不得直接 commit、直接改模拟盘、直接写策略、直接绕过 approval。

---

## 七、Context / Message 接入

Context 只加入 handoff_refs、latest_handoff_trace_id、handoff_role_summaries。

MessageBus 新增或复用：HANDOFF_REQUESTED、HANDOFF_ACCEPTED、HANDOFF_RESULT、HANDOFF_BLOCKED。payload 只包含 handoff_id、source_role、target_role、status、summary、refs、blocked_reason。

---

## 八、UI 接入

AI Agent 页面显示 handoff_count、roles_used、latest_handoff_status、safe_handoff_summary。系统监控显示 Handoff health、latest handoff count、blocked handoff count、role usage summary。所有 details 默认折叠 / 懒加载。

---

## 九、测试

新增：

```text
tests/unit/test_phase17_handoff_coordinator.py
tests/unit/test_phase17_handoff_executor_integration.py
tests/unit/test_phase17_handoff_ui_safe_summary.py
```

覆盖：Critic HANDOFF_REQUESTED 触发 handoff；证据不足路由到 EVIDENCE_RETRIEVER；调仓建议路由到 PORTFOLIO_ANALYST/RISK_ANALYST/STRATEGY_GUARD；Specialist 不能调用 blocked tools；depth limit 生效；Context 只携带 refs；MessageBus 产生 HANDOFF_*；secret 不进入 handoff/message/UI；WriteGateway 不被绕过。

运行：

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
py -3 -m pytest tests/unit/test_phase17_handoff_core.py tests/unit/test_phase17_handoff_policy_router.py tests/unit/test_phase17_handoff_coordinator.py tests/unit/test_phase17_handoff_executor_integration.py tests/unit/test_phase17_handoff_ui_safe_summary.py -q
py -3 -m pytest tests/unit/test_phase16_critic_executor_integration.py tests/unit/test_phase16_reflection_ui_safe_summary.py -q
py -3 -m pytest tests/unit/test_phase15_agent_chat_loading.py -q
```

---

## 十、真实网页功能检查

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

额外测试输入：

```text
综合分析我的当前持仓风险，并给出是否需要调仓的建议
帮我检查这个调仓建议是否证据充分
为什么上次建议调仓，分别从风险、证据、组合角度解释
```

必须记录：input、actual_summary、handoff_created、roles_seen、handoff_messages_seen、critic_after_handoff_seen、secret_visible、traceback_error、pass/fail。

---

## 十一、阶段报告

生成：`docs/phase17_c_handoff_runtime_integration_report.md`

必须包含：Coordinator 能力、SpecialistAdapter 能力、Executor/Context/MessageBus/UI 接入点、Role 实际产生情况、WriteGateway 边界说明、兼容旧接口说明、真实网页功能检查记录、测试结果、`NEXT_STAGE_ALLOWED = true / false`。

---

## 十二、验收标准

1. HandoffCoordinator / SpecialistAdapter 建立；
2. Executor 可触发受控 handoff；
3. HANDOFF_* messages 可记录；
4. Context 只携带 handoff refs；
5. Specialist 不能直接写业务状态；
6. WriteGateway 不被绕过；
7. AI Agent / 系统监控可显示 safe handoff summary；
8. 长对话加载优化不退化；
9. secret 不进入 handoff/message/UI；
10. 真实网页和测试通过；
11. NEXT_STAGE_ALLOWED = true。
