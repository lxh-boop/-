# Phase 12-E：UI 接入与真实网页功能检查

## 本阶段目标

在主链接入 ContextManager 后，做最小 UI 接入，并建立真实网页功能检查流程。

目标：

```text
AI Agent 页面创建/恢复 context
页面可显示 context_id / run_id / trace_id 的安全摘要
待确认方案仍正常显示
上下文不泄露 secret
建立网页功能检查脚本或检查清单
```

---

## 一、允许做

1. 小范围修改 AI Agent 页面；
2. 小范围修改系统监控页面；
3. 可新增 context debug 展示，但默认折叠；
4. 可新增网页检查脚本；
5. 可新增页面 smoke test 文档；
6. 可新增 Playwright/Selenium 测试，如环境支持。

---

## 二、禁止做

1. 不大改页面布局；
2. 不删除旧 session_state；
3. 不在页面显示 confirmation_token 原文；
4. 不在页面显示 API key / DB path；
5. 不让页面直接写业务状态；
6. 不重写 AI 模拟盘页面核心逻辑；
7. 不改变用户操作流程。

---

## 三、UI 接入要求

### AI Agent 页面

要求：

```text
创建或恢复 ContextBundle
显示安全 context summary
保留聊天功能
保留 proposal 展示
保留确认按钮
确认仍走 Write Gateway
```

可显示：

```text
context_id
run_id
trace_id
current_task_count
artifact_ref_count
pending_approval_exists
```

不可显示：

```text
confirmation_token 原文
API key
DB path
内部堆栈
完整大对象
```

### 系统监控页面

可新增：

```text
Context health
Latest context snapshots
Artifact refs count
Runtime trace count
```

只显示安全摘要。

---

## 四、真实网页检查脚本

优先新增：

```text
scripts/check_phase12_context_web.py
```

如果项目环境支持 Playwright/Selenium，则自动检查：

```text
health
首页
AI Agent
AI 模拟盘
系统监控
```

如果不支持浏览器自动化，则脚本至少检查 health，并输出手工检查清单。

检查清单必须包括：

```text
页面是否打开
是否有 Traceback
是否有 ModuleNotFoundError
是否有 NameError
是否有 KeyError
是否能输入 AI Agent 问题
是否能返回结果
是否能生成 proposal
是否显示 token 原文
```

---

## 五、测试

新增：

```text
tests/unit/test_phase12_context_ui_safe_summary.py
```

覆盖：

```text
context summary 不含 secret
context summary 不含 token
context summary 不含 DB path
pending approval 只显示摘要
UI helper 对空 context 安全
```

运行：

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase12_context_ui_safe_summary.py -q
py -3 -m pytest tests/unit/test_phase12_context_executor_integration.py -q
py -3 -m pytest tests/unit/test_phase12_context_tool_executor.py -q
py -3 -m pytest tests/unit/test_phase12_context_policy.py -q
py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q
py -3 -m pytest tests/unit/test_agent_write_requires_confirmation.py -q
```

---

## 六、真实网页功能检查

必须真实执行。

检查：

```text
python -m streamlit run app.py
http://127.0.0.1:8501/_stcore/health
```

页面：

```text
首页
AI Agent 页面
AI 模拟盘页面
系统监控页面
报告页面，如存在
```

AI Agent 实际输入：

```text
查看我的当前持仓
分析当前组合风险
给我一个调仓建议
查看系统状态
```

必须记录：

```text
input
actual_summary
whether_context_created
whether_secret_visible
whether_traceback
pass/fail
```

---

## 七、阶段报告

生成：

```text
docs/phase12_e_context_ui_web_check_report.md
```

必须包含：

```text
UI 修改点
Context summary 字段
安全过滤结果
网页检查方法
网页检查记录
测试结果
NEXT_STAGE_ALLOWED = true / false
```

---

## 八、验收标准

1. AI Agent 页面可创建/恢复 context；
2. context safe summary 可展示或可调试查看；
3. confirmation_token 不在页面显示；
4. 页面不显示 API key / DB path；
5. AI Agent 四个真实输入测试通过；
6. AI 模拟盘页面不报错；
7. 系统监控页面不报错；
8. 网页检查记录完整；
9. 测试通过；
10. NEXT_STAGE_ALLOWED = true。
