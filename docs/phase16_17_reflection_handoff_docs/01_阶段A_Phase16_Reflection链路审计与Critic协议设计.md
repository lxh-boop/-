# Phase 16-A：Reflection 链路审计与 Critic 协议设计

## 本阶段目标

本阶段先不要大规模改代码，重点是审计当前哪些结果需要被 Critic 审查，并设计 ReflectionCritic / CriticResult 的目标协议。

目标：

```text
找出 Agent 最终回答如何生成
找出 proposal / 调仓建议如何生成
找出 Observation / Replan / MessageTrace / Memory refs 如何进入最终结果
找出工具失败、空结果、证据不足、审批需求如何表达
找出 UI 当前如何展示安全摘要
设计 ReflectionCritic 协议
设计 CriticAction / CriticIssue / CriticPolicy
设计后续接入点
```

---

## 一、允许做

1. 搜索和阅读代码；
2. 新增 Reflection 链路审计报告；
3. 设计 CriticResult 字段；
4. 设计 CriticAction / CriticIssue / CriticSeverity；
5. 设计 CriticPolicy；
6. 设计 CriticEngine 接入点；
7. 可以新增 `agent/reflection/README.md` 或设计草案；
8. 可以新增空包或类型草案，但不要接入主链。

---

## 二、禁止做

1. 不接入 executor 主链；
2. 不改 ToolExecutor 行为；
3. 不改 WriteGateway；
4. 不改 ContextManager；
5. 不改 MemoryManager；
6. 不改 UI 逻辑；
7. 不改数据库 schema；
8. 不实现 Multi-Agent Handoff；
9. 不让 Critic 调用写工具；
10. 不改变业务结果。

---

## 三、必须检查的文件

```text
agent/executor.py
agent/tool_engine.py
agent/write_gateway.py
agent/context/
agent/communication/
agent/react/
agent/memory/
agent/artifacts.py
agent/goal_planning.py
agent/orchestration/multi_task_executor.py
agent/tools/
app/pages/ai_agent.py
app/pages/system_monitor.py
app/pages/ai_paper_trading.py
```

---

## 四、必须输出 Reflection 链路审计表

生成：

```text
docs/phase16_a_reflection_audit_report.md
```

表格字段：

```text
reflection_source
file
function_or_class
target_to_critic
available_refs
contains_observation
contains_replan
contains_message_trace
contains_memory_ref
contains_tool_result
contains_approval
contains_secret_risk
used_by_llm
used_by_ui
critic_check_needed
planned_critic_issue
planned_critic_action
migration_phase
```

至少覆盖：

```text
final report
portfolio proposal
tool result summary
observation event
replan decision
message trace
memory safe summary
approval required result
RAG/news/evidence result
risk analysis result
system status result
AI Agent rendered answer
```

---

## 五、设计 ReflectionCritic 协议

建议目标模型：

```text
CriticResult
CriticIssue
CriticAction
CriticSeverity
CriticTargetType
CriticPolicy
CriticSanitizer
CriticWindow
CriticEngine
CriticStore / ReflectionStore（可选轻量 jsonl）
```

建议 `CriticResult` 字段：

```text
critic_id
conversation_id
run_id
task_id
target_type
target_ref
target_summary
verdict
action
severity
score
issues
evidence_refs
observation_refs
replan_refs
message_refs
memory_refs
approval_refs
revision_instruction
replan_hint
handoff_hint
requires_user_confirmation
created_at
metadata
```

建议 `CriticAction`：

```text
PASS
REVISE_ANSWER
REPLAN_READONLY
ASK_USER
REQUIRE_APPROVAL
BLOCK_AND_REPORT
HANDOFF_REQUESTED
```

建议检查项：

```text
evidence_sufficiency
tool_success
context_completeness
risk_profile_alignment
write_gateway_boundary
approval_boundary
answer_consistency
uncertainty_disclosure
stale_data
hallucination_risk
memory_conflict
portfolio_risk_overreach
```

---

## 六、真实网页基线检查

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

## 七、测试命令

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

## 八、阶段报告

生成：`docs/phase16_a_reflection_audit_report.md`

必须包含：Reflection 链路审计表、CriticResult 字段设计、CriticAction 设计、CriticPolicy 设计、接入点设计、敏感字段风险识别、测试结果、网页检查结果、`NEXT_STAGE_ALLOWED = true / false`。

---

## 九、验收标准

1. 完成 Reflection 链路审计表；
2. 完成 CriticResult / CriticAction / CriticPolicy 设计；
3. 完成接入点设计；
4. 未破坏现有代码；
5. compileall 通过；
6. 回归测试通过；
7. 真实网页检查通过；
8. NEXT_STAGE_ALLOWED = true。
