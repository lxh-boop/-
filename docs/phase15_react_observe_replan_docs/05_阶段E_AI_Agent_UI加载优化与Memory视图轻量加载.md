# Phase 15-E：AI Agent UI 加载优化与 Memory 视图轻量加载

## 本阶段目标

在 ReAct Observe / Replan 接入后，修复 AI Agent 对话页面消息超过约 7 条后明显卡顿、加载变慢的问题，并让页面可以安全查看 ReAct trace / observation / memory safe summary 的轻量摘要。

目标：

```text
AI Agent 页面默认只渲染最近消息窗口
历史消息分页加载
message trace / react trace / tool details / evidence details 懒加载
Memory 只默认展示 safe summary
Context 注入控制 memory / observation 预算
系统监控页面展示 ReAct / Memory / Message health 轻量摘要
真实网页检查流程固定
```

---

## 一、允许做

1. 小范围修改 AI Agent 页面；
2. 小范围修改系统监控页面；
3. 可新增 ReAct Trace 折叠展示；
4. 可新增 observation debug helper；
5. 可新增分页查询 helper；
6. 可新增短 TTL cache helper；
7. 可新增网页检查脚本或扩展已有脚本；
8. 可新增 UI 性能测试；
9. 可新增 Memory safe summary 分页展示。

---

## 二、禁止做

1. 不大改页面布局；
2. 不删除旧 session_state；
3. 不在页面显示 confirmation_token 原文；
4. 不在页面显示 API key / DB path；
5. 不显示 artifact 文件路径；
6. 不显示内部堆栈；
7. 不显示 raw_positions / raw_evidence / raw_tool_payload；
8. 不让页面直接写业务状态；
9. 不改变用户操作流程；
10. 不默认全量加载历史消息；
11. 不默认全量加载 memory records；
12. 不默认全量展开工具轨迹；
13. 不把加载优化做成删除功能。

---

## 三、AI Agent 页面加载策略

必须实现或检查已有实现：

```text
默认只加载最近 8~10 条对话消息
提供“加载更早消息”按钮或分页控件
分页游标放入 session_state
每次新输入后只追加当前消息和回答，不重建全部历史卡片
消息内容分为 summary view 和 detail view
detail view 默认折叠
```

消息列表可以显示：

```text
time
role
summary
status
message_type_count
observation_count
replan_count
```

不可默认显示：

```text
完整 message payload
完整 tool result
完整 evidence chunk
完整 memory record
完整 developer details
```

---

## 四、ReAct Trace / Observation 展示

可以显示：

```text
react_trace_id
observation_count
last_observation_type
blocking_observation_count
replan_count
last_replan_reason
last_replan_scope
```

可以折叠展示安全列表：

```text
time
observation_type
severity
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
raw positions
raw evidence
```

---

## 五、Memory 视图轻量加载

默认只展示 Memory safe summary：

```text
memory_record_count
working_memory_count
long_term_memory_count
top_topics
last_updated
readonly_status
not_committed
```

如果用户展开 Memory records：

```text
只分页展示安全摘要
每页默认 5~10 条
不显示 metadata 中的敏感字段
不显示本地路径
不显示 raw evidence / raw positions
```

Context 注入要求：

```text
只注入必要 memory refs
只注入 top-k safe memory summaries
不注入完整 memory store
不注入完整 historical conversation
不注入 raw payload
```

---

## 六、缓存与 session_state

允许使用短 TTL cache 缓存稳定查询：

```text
message trace summary
react trace summary
memory safe summary
system health summary
分页查询结果摘要
```

要求：

```text
cache key 必须包含 user_id / conversation_id / run_id / page cursor
TTL 不要过长，建议 10~60 秒
写操作或新消息后必须能刷新相关 summary
session_state 只保存 UI 控件状态、分页游标、当前 run_id
不要把 raw tool payload / raw memory records 放入 session_state
```

---

## 七、系统监控页面接入

可显示：

```text
ReAct health
latest run observation count
latest run replan count
ObserveStore safe summary
MessageBus health
MemoryStore health
AI Agent chat page loaded_message_count
AI Agent chat page visible_message_window
```

路径只能显示安全摘要，不显示完整本地路径。

---

## 八、真实网页检查脚本

新增或扩展：

```text
scripts/check_phase15_react_loading_web.py
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
是否产生 observation 摘要
是否产生 replan 摘要或 skipped 摘要
是否默认只显示最近消息窗口
是否能加载更早消息
是否能折叠/展开 ReAct trace
是否能折叠/展开 Memory safe summary
是否泄露 token/API key/db path/stack/raw payload
```

---

## 九、测试

新增：

```text
tests/unit/test_phase15_agent_chat_loading.py
tests/unit/test_phase15_react_ui_safe_trace.py
tests/unit/test_phase15_memory_view_loading.py
```

覆盖：

```text
默认消息窗口不超过配置值
分页查询能加载更早消息
empty history 安全
message trace summary 不含 secret
react trace summary 不含 token
memory safe summary 不含 DB path
memory records 分页不含 artifact path
pending approval 只显示摘要
session_state 不保存 raw payload
cache helper 可以被显式刷新
```

运行：

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase15_agent_chat_loading.py -q
py -3 -m pytest tests/unit/test_phase15_react_ui_safe_trace.py -q
py -3 -m pytest tests/unit/test_phase15_memory_view_loading.py -q
py -3 -m pytest tests/unit/test_phase15_replan_executor_integration.py -q
py -3 -m pytest tests/unit/test_phase15_observe_tool_executor_integration.py -q
py -3 -m pytest tests/unit/test_phase14_memory_tool_ui.py -q
py -3 -m pytest tests/unit/test_phase13_message_ui_safe_trace.py -q
py -3 -m pytest tests/unit/test_phase12_context_ui_safe_summary.py -q
py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q
```

---

## 十、真实网页功能检查

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
我上次为什么建议调仓？
```

长对话检查：

```text
连续输入不少于 12 条消息
确认页面默认只渲染最近消息窗口
点击加载更早消息
展开/折叠 ReAct trace
展开/折叠 Memory safe summary
刷新页面后再次检查
切换到系统监控再切回 AI Agent
```

必须记录：

```text
input
actual_summary
visible_message_count
history_pagination_visible
react_trace_visible
memory_summary_visible
secret_visible
traceback_error
load_issue_observed
pass/fail
```

---

## 十一、阶段报告

生成：

```text
docs/phase15_e_ui_loading_memory_view_report.md
```

必须包含：

```text
UI 修改点
消息分页策略
ReAct trace summary 字段
Memory safe summary 字段
缓存策略
session_state 使用说明
安全过滤结果
网页检查方法
网页检查记录
长对话检查记录
测试结果
NEXT_STAGE_ALLOWED = true / false
```

---

## 十二、验收标准

1. AI Agent 页面默认只展示最近消息窗口；
2. 历史消息可分页加载；
3. ReAct trace 安全摘要可展示；
4. Observation 安全摘要可展示；
5. Memory safe summary 可展示；
6. Memory records 不默认全量加载；
7. confirmation_token 不在页面显示；
8. API key / DB path / artifact path 不在页面显示；
9. raw payload / raw evidence / raw positions 不在页面显示；
10. AI Agent 五个真实输入测试通过；
11. 12 条以上长对话检查通过；
12. AI 模拟盘页面不报错；
13. 系统监控页面不报错；
14. 网页检查记录完整；
15. 测试通过；
16. NEXT_STAGE_ALLOWED = true。
