# Phase 13-C：MessageStore、MessageBus、MessageRouter

## 本阶段目标

建立消息存储、消息总线和消息路由能力，但仍以轻量本地实现为主。

目标：

```text
MessageStore
MessageBus
MessageRouter
MessageTrace
MessageSubscription
Message delivery policy
```

本阶段可以建立可用的通信底座，但不要强行把所有业务链路一次性切过来。

---

## 一、允许做

1. 新增 MessageStore；
2. 新增 MessageBus；
3. 新增 MessageRouter；
4. 新增 MessageTrace；
5. 增加消息发布/订阅基础能力；
6. 增加消息查询；
7. 增加单测。

---

## 二、禁止做

1. 不引入外部消息队列；
2. 不引入 Celery / Redis / Kafka；
3. 不改业务算法；
4. 不让 MessageBus 直接写业务状态；
5. 不让 MessageBus 绕过 ToolExecutor；
6. 不让 MessageBus 绕过 WriteGateway；
7. 不实现完整 Multi-Agent；
8. 不大改 UI。

---

## 三、建议新增文件

```text
agent/communication/message_store.py
agent/communication/message_bus.py
agent/communication/message_router.py
agent/communication/message_trace.py
```

---

## 四、MessageStore

必须支持：

```text
save_message()
load_message()
list_messages_by_run()
list_messages_by_conversation()
list_messages_by_task()
append_trace_event()
expire_messages()
```

存储方式：

```text
优先文件型或轻量 SQLite
可复用 outputs/message_logs/<user_id>/<run_id>.jsonl
不强制新增复杂 schema
如需 schema 变更，必须最小化并写入报告
```

保存前必须：

```text
sanitize_for_audit()
```

secret 不得原文落盘。

---

## 五、MessageBus

必须支持：

```text
publish(message)
publish_many(messages)
subscribe(message_type, handler)
dispatch(envelope)
get_trace(run_id)
```

本阶段可以同步执行，不要求异步。

要求：

```text
publish 后写 MessageStore
dispatch 失败生成 ERROR_RAISED message
支持 no-op handler
支持 message_id 去重
```

---

## 六、MessageRouter

必须支持：

```text
route_message(message)
route_to_executor()
route_to_tool_executor()
route_to_write_gateway()
route_to_ui()
route_to_audit()
```

注意：

```text
Router 只决定消息去哪里
Router 不直接执行业务写操作
```

---

## 七、MessageTrace

必须支持：

```text
trace_id
run_id
message_ids
parent_child_edges
tool_call_edges
artifact_edges
approval_edges
errors
warnings
```

用于后续：

```text
ReAct Observe
Reflection
Multi-Agent Handoff
Debug UI
```

---

## 八、测试

新增：

```text
tests/unit/test_phase13_message_store_bus.py
tests/unit/test_phase13_message_router_trace.py
```

覆盖：

```text
save/load message
list messages by run/conversation/task
publish message writes store
dispatch no-op handler
dispatch error creates ERROR_RAISED
router returns expected channel
trace can build parent-child edges
secret 不落盘
```

运行：

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase13_message_store_bus.py -q
py -3 -m pytest tests/unit/test_phase13_message_router_trace.py -q
py -3 -m pytest tests/unit/test_phase13_message_core.py -q
py -3 -m pytest tests/unit/test_phase13_message_policy.py -q
py -3 -m pytest tests/unit/test_phase12_context_executor_integration.py -q
```

---

## 九、真实网页检查

检查：

```text
http://127.0.0.1:8501/_stcore/health
首页 / 预测排名
AI Agent 页面
AI 模拟盘页面
系统监控页面
```

本阶段未深接主链，页面行为应保持不变。

---

## 十、阶段报告

生成：

```text
docs/phase13_c_message_store_bus_report.md
```

必须包含：

```text
MessageStore 存储方式
MessageBus 能力
MessageRouter 规则
MessageTrace 结构
测试结果
网页检查结果
NEXT_STAGE_ALLOWED = true / false
```

---

## 十一、验收标准

1. MessageStore 建立；
2. MessageBus 建立；
3. MessageRouter 建立；
4. MessageTrace 建立；
5. 消息发布可落盘；
6. secret 不落盘；
7. dispatch error 可生成错误消息；
8. 测试通过；
9. 真实网页检查通过；
10. NEXT_STAGE_ALLOWED = true。
