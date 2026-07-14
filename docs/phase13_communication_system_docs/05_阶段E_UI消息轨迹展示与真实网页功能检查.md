# Phase 13-E：UI 消息轨迹展示与真实网页功能检查

## 本阶段目标

在主链接入 MessageBus 后，做最小 UI 接入，让页面可以安全查看本轮消息轨迹摘要。

目标：

```text
AI Agent 页面展示 message trace 安全摘要
系统监控页面展示 message bus health
消息轨迹不泄露 secret
真实网页检查流程固定
```

---

## 一、允许做

1. 小范围修改 AI Agent 页面；
2. 小范围修改系统监控页面；
3. 可新增 Message Trace 折叠展示；
4. 可新增 message debug helper；
5. 可新增网页检查脚本或扩展已有脚本；
6. 可新增 UI 安全测试。

---

## 二、禁止做

1. 不大改页面布局；
2. 不删除旧 session_state；
3. 不在页面显示 confirmation_token 原文；
4. 不在页面显示 API key / DB path；
5. 不显示 artifact 文件路径；
6. 不显示内部堆栈；
7. 不让页面直接写业务状态；
8. 不改变用户操作流程。

---

## 三、AI Agent 页面接入

可以显示：

```text
message_trace_id
message_count
last_message_type
tool_call_count
error_count
approval_message_count
artifact_message_count
```

可以折叠展示安全消息列表：

```text
time
message_type
sender
receiver
status
summary
refs
```

不可显示：

```text
raw confirmation_token
api key
db path
local file path
raw stack trace
raw tool payload 大对象
```

---

## 四、系统监控页面接入

可显示：

```text
MessageBus health
latest run message count
message store path safe summary
error message count
pending approval message count
```

路径只能显示安全摘要，不显示完整本地路径。

---

## 五、真实网页检查脚本

新增或扩展：

```text
scripts/check_phase13_communication_web.py
```

如果支持 Playwright/Selenium，自动检查：

```text
health
首页
AI Agent
AI 模拟盘
系统监控
```

如果不支持浏览器自动化，至少检查 health，并输出手工检查清单。

检查清单必须包括：

```text
页面是否打开
是否有 Traceback
是否有 ModuleNotFoundError
是否有 NameError
是否有 KeyError
是否能输入 AI Agent 问题
是否产生消息轨迹摘要
是否泄露 token/API key/db path/stack
```

---

## 六、测试

新增：

```text
tests/unit/test_phase13_message_ui_safe_trace.py
```

覆盖：

```text
message trace summary 不含 secret
message trace summary 不含 token
message trace summary 不含 DB path
message trace summary 不含 artifact path
UI helper 对空 message trace 安全
pending approval message 只显示摘要
```

运行：

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase13_message_ui_safe_trace.py -q
py -3 -m pytest tests/unit/test_phase13_message_executor_integration.py -q
py -3 -m pytest tests/unit/test_phase13_message_tool_executor_integration.py -q
py -3 -m pytest tests/unit/test_phase13_message_write_gateway_integration.py -q
py -3 -m pytest tests/unit/test_phase13_message_policy.py -q
py -3 -m pytest tests/unit/test_phase12_context_ui_safe_summary.py -q
py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q
```

---

## 七、真实网页功能检查

必须真实执行。

启动：

```text
python -m streamlit run app.py
```

检查：

```text
http://127.0.0.1:8501/_stcore/health
```

页面：

```text
首页 / 预测排名
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
message_trace_visible
message_types_seen
secret_visible
traceback_error
pass/fail
```

---

## 八、阶段报告

生成：

```text
docs/phase13_e_message_ui_web_check_report.md
```

必须包含：

```text
UI 修改点
Message trace summary 字段
安全过滤结果
网页检查方法
网页检查记录
测试结果
NEXT_STAGE_ALLOWED = true / false
```

---

## 九、验收标准

1. AI Agent 页面可展示 safe message trace；
2. 系统监控页面可展示 message bus health；
3. confirmation_token 不在页面显示；
4. API key / DB path / artifact path 不在页面显示；
5. AI Agent 四个真实输入测试通过；
6. AI 模拟盘页面不报错；
7. 系统监控页面不报错；
8. 网页检查记录完整；
9. 测试通过；
10. NEXT_STAGE_ALLOWED = true。
