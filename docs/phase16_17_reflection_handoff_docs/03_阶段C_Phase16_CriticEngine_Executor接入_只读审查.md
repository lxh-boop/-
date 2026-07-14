# Phase 16-C：CriticEngine、Executor 接入与只读审查

## 本阶段目标

把 Reflection Critic 以最小侵入方式接入 Agent 主链：在最终回答或 proposal 返回前后做只读审查，生成 CriticResult 和安全消息，但不直接写业务状态。

目标：

```text
新增 CriticEngine
CriticEngine 基于 refs 和 summary 审查，不读取 raw payload
Executor 生成最终结果后调用 CriticEngine
MessageBus 发布 REFLECTION_REQUESTED / REFLECTION_RESULT
Critic 可建议 revise / replan_readonly / ask_user / require_approval / block / handoff
不自动提交任何写操作
```

---

## 一、允许做

1. 新增 `agent/reflection/critic_engine.py`；
2. 可新增轻量 `ReflectionStore`，使用 jsonl，不改业务数据库 schema；
3. 最小修改 `agent/executor.py`；
4. 最小扩展 `agent/communication/message_types.py`；
5. 可复用 Observation / Replan / Message / Memory refs；
6. 增加集成测试。

---

## 二、禁止做

1. 不让 Critic 调用 commit；
2. 不让 Critic 调用写工具；
3. 不让 Critic 修改持仓、资金、策略；
4. 不绕过 WriteGateway；
5. 不重写 Planner / ToolExecutor；
6. 不改变 `UnifiedToolResult`；
7. 不把私有链式思考写入日志或 UI；
8. 不实现 Multi-Agent Handoff 运行时，仅可输出 `HANDOFF_REQUESTED` action。

---

## 三、建议新增/修改文件

```text
agent/reflection/critic_engine.py
agent/reflection/reflection_store.py
agent/reflection/__init__.py
agent/executor.py
agent/communication/message_types.py
tests/unit/test_phase16_critic_engine.py
tests/unit/test_phase16_critic_executor_integration.py
```

---

## 四、CriticEngine

必须支持：

```text
criticize_final_result()
criticize_tool_result_summary()
criticize_portfolio_proposal()
criticize_risk_analysis()
criticize_replan_decision()
build_critic_context_from_refs()
```

输入只允许 final answer summary、result status、observation_refs、replan_refs、message_refs、memory_refs、approval_refs、artifact/evidence refs、risk profile safe summary。不得输入 raw tool payload、raw positions、raw evidence、confirmation_token、api_key、db_path、local path、stack trace、private chain-of-thought。

---

## 五、Executor 接入

在 final report / proposal 准备返回前后执行：

```text
critic_result = CriticEngine.criticize_final_result(...)
```

根据 `CriticAction`：

```text
PASS -> 原样返回，可附带 critic pass 摘要
REVISE_ANSWER -> 只修改最终回答文本，不改业务结果
REPLAN_READONLY -> 触发现有 ReplanPolicy 的只读返工建议；本阶段可先只生成提示，不强制循环
ASK_USER -> 返回一个必要澄清问题
REQUIRE_APPROVAL -> 返回需确认提示，仍走 WriteGateway
BLOCK_AND_REPORT -> 阻断危险输出并说明原因
HANDOFF_REQUESTED -> 只记录 handoff_hint，Phase 17 接入后再路由
```

CriticEngine 异常时：原流程继续，但记录 `phase16_critic_failed` warning，不能导致页面崩溃。

---

## 六、MessageBus 接入

如果 `REFLECTION_REQUESTED` / `REFLECTION_RESULT` 缺失则最小补充。payload 只包含 critic_id、verdict、action、severity、score、issue_count、summary、refs。

---

## 七、测试

新增：

```text
tests/unit/test_phase16_critic_engine.py
tests/unit/test_phase16_critic_executor_integration.py
```

覆盖：证据不足 -> REPLAN_READONLY；工具失败但答案确定 -> REVISE_ANSWER；写操作无审批 -> REQUIRE_APPROVAL / BLOCK_AND_REPORT；安全结果 -> PASS；CriticEngine 异常不破坏主流程；Executor 产生 REFLECTION_RESULT message；secret 不进入 critic result/message/UI。

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
py -3 -m pytest tests/unit/test_phase16_critic_core.py tests/unit/test_phase16_critic_policy.py tests/unit/test_phase16_critic_engine.py tests/unit/test_phase16_critic_executor_integration.py -q
py -3 -m pytest tests/unit/test_phase15_replan_executor_integration.py tests/unit/test_phase15_observe_tool_executor_integration.py -q
```

---

## 八、真实网页功能检查

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

额外记录：input、actual_summary、critic_result_created、critic_action_seen、reflection_message_seen、secret_visible、traceback_error、pass/fail。

---

## 九、阶段报告

生成：`docs/phase16_c_critic_engine_integration_report.md`

必须包含：CriticEngine 能力、Executor 接入点、MessageBus 接入点、CriticAction 实际产生情况、WriteGateway 边界说明、兼容旧接口说明、真实网页功能检查记录、测试结果、`NEXT_STAGE_ALLOWED = true / false`。

---

## 十、验收标准

1. CriticEngine 建立；
2. Executor 可调用 CriticEngine；
3. REFLECTION_REQUESTED / REFLECTION_RESULT 可记录；
4. Critic 不直接写业务状态；
5. WriteGateway 不被绕过；
6. secret 不进入 critic/message/UI；
7. AI Agent 真实输入测试通过；
8. 页面不报错；
9. 测试通过；
10. NEXT_STAGE_ALLOWED = true。
