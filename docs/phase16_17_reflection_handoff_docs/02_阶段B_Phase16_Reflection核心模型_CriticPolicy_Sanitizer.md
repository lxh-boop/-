# Phase 16-B：Reflection 核心模型、CriticPolicy、CriticSanitizer

## 本阶段目标

建立 Reflection Critic 的核心模型和安全策略，但暂不深度接入主执行链。

目标：

```text
新增 agent/reflection/
新增 CriticResult / CriticIssue
新增 CriticAction / CriticSeverity / CriticTargetType
新增 CriticPolicy
新增 CriticSanitizer
新增 CriticWindow
保证 Critic 结果可序列化、可脱敏、可裁剪、可审计
```

---

## 一、允许做

1. 新增 `agent/reflection/`；
2. 新增 reflection 数据类；
3. 新增枚举；
4. 新增 CriticPolicy；
5. 新增 CriticSanitizer；
6. 新增 CriticWindow；
7. 新增基础单元测试；
8. 保持旧接口兼容。

---

## 二、禁止做

1. 不接入 executor 主链；
2. 不改 ToolExecutor 默认行为；
3. 不改 WriteGateway；
4. 不改 ContextManager；
5. 不改 MemoryManager；
6. 不实现 Multi-Agent Handoff；
7. 不调用外部 Agent 框架；
8. 不训练模型、不微调模型；
9. 不大改 UI。

---

## 三、建议新增文件

```text
agent/reflection/__init__.py
agent/reflection/critic_types.py
agent/reflection/critic_policy.py
agent/reflection/critic_sanitizer.py
agent/reflection/critic_window.py
```

---

## 四、核心模型

### CriticResult 字段

```text
critic_id, conversation_id, run_id, task_id, target_type, target_ref, target_summary,
verdict, action, severity, score, issues, evidence_refs, observation_refs, replan_refs,
message_refs, memory_refs, approval_refs, revision_instruction, replan_hint, handoff_hint,
requires_user_confirmation, created_at, metadata
```

要求：可序列化、可脱敏、可裁剪、可审计；只保存 summary + refs；不得保存 raw payload、raw positions、raw evidence、confirmation_token 或私有链式思考。

### CriticAction

```text
PASS
REVISE_ANSWER
REPLAN_READONLY
ASK_USER
REQUIRE_APPROVAL
BLOCK_AND_REPORT
HANDOFF_REQUESTED
```

### CriticTargetType

```text
FINAL_REPORT
TOOL_RESULT
PORTFOLIO_PROPOSAL
RISK_ANALYSIS
REPLAN_DECISION
OBSERVATION_TRACE
MEMORY_SUMMARY
SYSTEM_STATUS
```

---

## 五、CriticPolicy

必须实现：

```text
classify_issue()
score_result()
decide_action()
can_show_to_llm()
can_show_to_ui()
requires_redaction()
```

规则：

```text
工具失败/空结果但答案确定性很高 -> REVISE_ANSWER 或 REPLAN_READONLY
证据不足 -> REPLAN_READONLY
缺少必要用户信息 -> ASK_USER
涉及写操作但未进入审批 -> REQUIRE_APPROVAL 或 BLOCK_AND_REPORT
存在 confirmation_token/API key/db path/stack/raw payload -> BLOCK_AND_REPORT + redaction
仓位建议过激且未检查风险偏好 -> REVISE_ANSWER 或 REQUIRE_APPROVAL
用户风险偏好冲突 -> REVISE_ANSWER / ASK_USER
高风险写操作 -> REQUIRE_APPROVAL
权限被阻断 -> BLOCK_AND_REPORT
```

---

## 六、CriticSanitizer

必须实现：

```text
sanitize_for_llm()
sanitize_for_ui()
sanitize_for_audit()
sanitize_for_context()
```

必须过滤：confirmation_token、API key、Tushare token、password、secret、authorization、cookie、db_path、本地绝对路径、stack_trace、Traceback、raw_positions、raw_evidence、raw_tool_payload、full_payload、private chain-of-thought。

---

## 七、CriticWindow

必须实现：`trim_critic_results_to_budget()`、`summarize_old_critic_results()`、`keep_blocking_issues()`、`estimate_critic_size()`。

---

## 八、测试

新增：

```text
tests/unit/test_phase16_critic_core.py
tests/unit/test_phase16_critic_policy.py
```

覆盖：CriticResult/Issue 创建与序列化、CriticAction 完整、secret 不进 LLM/UI、raw payload 只保留 summary + refs、CriticPolicy 对证据不足/写边界/工具失败给出正确 action、CriticWindow 保留 blocking issues。

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

生成：`docs/phase16_b_critic_core_report.md`

必须包含：新增文件、CriticResult 模型、CriticAction 列表、CriticPolicy 规则、CriticSanitizer 结果、CriticWindow 裁剪规则、测试结果、网页检查结果、`NEXT_STAGE_ALLOWED = true / false`。

---

## 十一、验收标准

1. `agent/reflection/` 建立；
2. CriticResult / CriticIssue / CriticAction 建立；
3. CriticPolicy / CriticSanitizer / CriticWindow 建立；
4. secret 不进 LLM/UI；
5. 大对象摘要 + ref；
6. compileall 和单测通过；
7. 真实网页检查通过；
8. NEXT_STAGE_ALLOWED = true。
