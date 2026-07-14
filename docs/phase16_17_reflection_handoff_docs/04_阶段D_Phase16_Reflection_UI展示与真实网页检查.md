# Phase 16-D：Reflection UI 展示与真实网页检查

## 本阶段目标

在 CriticEngine 接入后，做最小 UI 接入，让 AI Agent 页面和系统监控页面可以安全查看 Reflection Critic 摘要。

目标：AI Agent 页面展示 critic safe summary，默认不展开完整 details；系统监控展示 Reflection health；Critic details 懒加载；不泄露 secret；真实网页检查流程固定。

---

## 一、允许做

1. 小范围修改 `app/pages/ai_agent.py`；
2. 小范围修改 `app/pages/system_monitor.py`；
3. 可新增 reflection UI helper；
4. 可新增网页检查脚本或扩展已有脚本；
5. 可新增 UI 安全测试。

---

## 二、禁止做

1. 不大改页面布局；
2. 不删除旧 session_state；
3. 不显示 confirmation_token、API key、DB path、local path、raw tool payload、内部堆栈、private chain-of-thought；
4. 不让页面直接写业务状态；
5. 不改变用户操作流程；
6. 不破坏 Phase 15 长对话加载优化。

---

## 三、AI Agent 页面接入

可以显示：critic_id、critic_action、critic_severity、critic_score、issue_count、safe_summary、next_action_hint。

折叠展示安全 issue 列表：issue_type、severity、summary、recommended_action、refs。

---

## 四、系统监控页面接入

可显示 Reflection health、latest critic count、critic pass/fail count、blocking issue count、latest critic action。路径只能显示安全摘要，不显示完整本地路径。

---

## 五、真实网页检查脚本

新增或扩展：

```text
scripts/check_phase16_reflection_web.py
```

检查：页面是否打开；是否有 Traceback / ModuleNotFoundError / NameError / KeyError；是否能输入 AI Agent 问题；是否产生 Reflection summary；是否泄露 token/API key/db path/stack/raw payload；长对话默认窗口是否仍为 10 左右；加载更早是否仍可用。

---

## 六、测试

新增：

```text
tests/unit/test_phase16_reflection_ui_safe_summary.py
```

覆盖：critic summary 不含 secret/token/DB path/raw payload；UI helper 对空 critic 安全；blocking issue 只显示摘要；长对话窗口逻辑不被破坏。

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
py -3 -m pytest tests/unit/test_phase16_reflection_ui_safe_summary.py tests/unit/test_phase16_critic_executor_integration.py tests/unit/test_phase15_agent_chat_loading.py -q
py -3 scripts/check_phase16_reflection_web.py
py -3 scripts/check_phase15_react_loading_web.py
```

---

## 七、真实网页功能检查

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

必须记录：input、actual_summary、reflection_summary_visible、critic_action_seen、secret_visible、traceback_error、long_chat_window_ok、pass/fail。

---

## 八、阶段报告

生成：`docs/phase16_d_reflection_ui_web_check_report.md`

必须包含：UI 修改点、Reflection summary 字段、安全过滤结果、长对话加载回归结果、网页检查方法、网页检查记录、测试结果、`NEXT_STAGE_ALLOWED = true / false`。

---

## 九、验收标准

1. AI Agent 页面可展示 Reflection safe summary；
2. 系统监控页面可展示 Reflection health；
3. 敏感信息不在页面显示；
4. AI Agent 真实输入测试通过；
5. 长对话加载优化不退化；
6. AI 模拟盘和系统监控页面不报错；
7. 网页检查记录完整；
8. 测试通过；
9. NEXT_STAGE_ALLOWED = true。
