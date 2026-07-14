# Phase 17-B：Handoff 核心模型、Router、Policy、Sanitizer

## 本阶段目标

建立 Multi-Agent Handoff 的核心模型、路由规则和安全策略，但暂不深度接入主执行链。

目标：新增 `agent/handoff/`，实现 HandoffRequest / HandoffResult / HandoffTrace / AgentRole / HandoffPolicy / HandoffSanitizer / HandoffRouter，保证 handoff 可序列化、可脱敏、可裁剪、可审计。

---

## 一、允许做

1. 新增 `agent/handoff/`；
2. 新增 handoff 数据类和 AgentRole 枚举；
3. 新增 HandoffPolicy / HandoffSanitizer / HandoffRouter；
4. 新增基础单元测试；
5. 保持旧接口兼容。

---

## 二、禁止做

1. 不接入 executor 主链；
2. 不改 ToolExecutor / WriteGateway / ContextManager / MemoryManager；
3. 不调用外部 Agent 框架；
4. 不让 specialist 直接写业务状态；
5. 不大改 UI。

---

## 三、建议新增文件

```text
agent/handoff/__init__.py
agent/handoff/handoff_types.py
agent/handoff/handoff_policy.py
agent/handoff/handoff_sanitizer.py
agent/handoff/handoff_router.py
```

---

## 四、核心模型

AgentRole 至少包含：COORDINATOR、PORTFOLIO_ANALYST、RISK_ANALYST、EVIDENCE_RETRIEVER、STRATEGY_GUARD、REPORT_WRITER、SYSTEM_DIAGNOSTIC。

HandoffRequest 字段：handoff_id、conversation_id、run_id、task_id、source_role、target_role、reason、priority、input_summary、context_refs、message_refs、observation_refs、replan_refs、critic_refs、memory_refs、artifact_refs、approval_refs、allowed_tools、blocked_tools、requires_approval、created_at、metadata。

HandoffResult 字段：handoff_id、conversation_id、run_id、task_id、target_role、status、summary、findings、recommended_action、artifact_refs、message_refs、observation_refs、critic_refs、approval_refs、errors、warnings、created_at、metadata。

HandoffTrace 字段：trace_id、run_id、handoff_ids、role_edges、tool_edges、artifact_edges、critic_edges、approval_edges、errors、warnings。

---

## 五、HandoffPolicy

必须实现：`can_handoff()`、`allowed_tools_for_role()`、`blocked_tools_for_role()`、`requires_approval()`、`can_show_to_llm()`、`can_show_to_ui()`、`max_handoff_depth()`。

规则：PORTFOLIO_ANALYST 可读 portfolio state/proposal summary 但不能 commit；RISK_ANALYST 可读 risk summary 但不能改策略；EVIDENCE_RETRIEVER 可查 RAG/news/evidence 但不能写持仓；STRATEGY_GUARD 检查规则和审批边界但不能执行写操作；REPORT_WRITER 只能汇总 refs；SYSTEM_DIAGNOSTIC 只能读系统状态；所有写操作必须回到 COORDINATOR + WriteGateway。

---

## 六、HandoffRouter

必须支持：route_by_user_goal()、route_by_critic_action()、route_by_missing_context()、route_by_tool_need()、route_by_risk_level()。

示例：证据不足 -> EVIDENCE_RETRIEVER；风险不确定 -> RISK_ANALYST；调仓建议 -> PORTFOLIO_ANALYST + RISK_ANALYST + STRATEGY_GUARD；系统问题 -> SYSTEM_DIAGNOSTIC；最终报告 -> REPORT_WRITER；Critic action HANDOFF_REQUESTED -> 按 handoff_hint 路由。

---

## 七、HandoffSanitizer

必须过滤 confirmation_token、api_key、tushare_token、password、secret、db_path、local path、stack trace、raw positions、raw evidence、raw tool payload、private chain-of-thought。

---

## 八、测试

新增：

```text
tests/unit/test_phase17_handoff_core.py
tests/unit/test_phase17_handoff_policy_router.py
```

覆盖：HandoffRequest/Result 创建与序列化、AgentRole 完整、role 权限正确、路由正确、secret 不进入 LLM/UI、写工具不在 specialist allowed_tools 中、max handoff depth 生效。

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
py -3 -m pytest tests/unit/test_phase17_handoff_core.py tests/unit/test_phase17_handoff_policy_router.py -q
py -3 -m pytest tests/unit/test_phase16_critic_core.py tests/unit/test_phase16_critic_policy.py -q
```

---

## 九、真实网页检查

本阶段未接入主链，页面行为应保持不变。

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

## 十、阶段报告

生成：`docs/phase17_b_handoff_core_report.md`

必须包含：新增文件、HandoffRequest 模型、HandoffResult 模型、AgentRole 列表、HandoffPolicy 规则、HandoffRouter 规则、HandoffSanitizer 结果、测试结果、网页检查结果、`NEXT_STAGE_ALLOWED = true / false`。

---

## 十一、验收标准

1. `agent/handoff/` 建立；
2. HandoffRequest / HandoffResult / HandoffTrace / AgentRole 建立；
3. HandoffPolicy / HandoffRouter / HandoffSanitizer 建立；
4. specialist 不能直接写业务状态；
5. secret 不进 LLM/UI；
6. compileall / 单测通过；
7. 真实网页检查通过；
8. NEXT_STAGE_ALLOWED = true。
