# Phase 14-E：Context、Message、Tool、UI 接入

## 本阶段目标

把 MemoryManager 以兼容方式接入现有 Agent Runtime。

目标：

```text
ContextManager 可读取相关 memory refs
MessageTrace 可写入 EpisodicMemory candidate
Artifact 可生成 Evidence/Portfolio memory candidate
新增 MemoryTool 只读工具
注册 ToolDefinition：memory.search、memory.get_summary
AI Agent 页面展示 Memory 安全摘要
系统监控展示 MemoryStore Health
```

## 允许做

```text
接入 ContextManager 的 MemoryContext
接入 MessageBus / MessageTrace
接入 Artifact
新增 MemoryTool 只读工具
注册 memory.search 和 memory.get_summary
UI 展示 memory safe summary
系统监控展示 MemoryStore Health
增加测试
保持旧接口兼容
```

## 禁止做

```text
不让 MemoryManager 写业务状态
不让 MemoryTool commit
不改变 WriteGateway
不改模拟盘算法
不把所有消息无差别写记忆
不让 LLM 直接写长期记忆
不显示 secret
不大改页面
```

## 建议新增/修改文件

```text
agent/memory/memory_context_bridge.py
agent/memory/memory_tool.py
agent/tool_engine.py
agent/context/context_builder.py
app/pages/ai_agent.py
app/pages/system_monitor.py
tests/unit/test_phase14_memory_context_integration.py
tests/unit/test_phase14_memory_message_integration.py
tests/unit/test_phase14_memory_tool_ui.py
```

## 关键实现要求

### 1. 安全要求

```text
confirmation_token 不可写入长期记忆
api_key / tushare_token / password / secret 不可写入长期记忆
db_path / 本地绝对路径 不进入 LLM/UI memory view
stack_trace / traceback 不进入 LLM/UI memory view
raw_positions / raw_evidence / raw tool payload 不直接长期保存
pending plan 只保存 plan_id/status/token_present/summary
```

### 2. 与现有系统关系

```text
MemoryManager 不替代 ContextManager
MemoryManager 不替代 MessageBus
MemoryManager 不替代 ArtifactStore
MemoryManager 不替代 EvidenceService
MemoryManager 不拥有写业务状态权限
WriteGateway 仍是唯一写操作确认入口
```

### 3. 测试命令

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase14_memory_context_integration.py -q
py -3 -m pytest tests/unit/test_phase14_memory_message_integration.py -q
py -3 -m pytest tests/unit/test_phase14_memory_tool_ui.py -q
py -3 -m pytest tests/unit/test_phase14_memory_manager.py -q
py -3 -m pytest tests/unit/test_phase13_message_store_bus.py -q
py -3 -m pytest tests/unit/test_phase12_context_executor_integration.py -q
py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q
```


## 真实网页检查

必须检查：

```text
http://127.0.0.1:8501/_stcore/health
首页 / 预测排名
AI Agent 页面
AI 模拟盘页面
系统监控页面
```

AI Agent 至少输入：

```text
查看我的当前持仓
分析当前组合风险
给我一个调仓建议
查看系统状态
```

从 Phase 14-E 开始，还必须输入：

```text
我更偏好稳健一点，记住这个偏好
我上次为什么建议调仓？
```

报告必须记录：

```text
WEB_CHECK_DONE = true
WEB_CHECK_METHOD = playwright / selenium / Streamlit AppTest / manual+health
WEB_CHECK_PAGES = [...]
WEB_CHECK_RESULT = PASS / FAIL
WEB_CHECK_ERRORS = [...]
```

不能出现：

```text
Traceback
ModuleNotFoundError
NameError
KeyError
confirmation_token
api_key
tushare_token
agent_quant.db
本地绝对路径
内部堆栈
```


## 阶段报告

生成：

```text
docs/phase14_e_memory_integration_ui_report.md
```

报告必须包含：

```text
阶段目标
新增/修改文件
核心实现说明
安全过滤结果
测试命令与结果
真实网页检查结果
失败项
未完成项
NEXT_STAGE_ALLOWED = true / false
```

## 验收标准

```text
MemoryContext 接入
MessageTrace 可产生 memory candidate
Artifact 可产生 memory candidate
memory.search 工具可用
memory.get_summary 工具可用
MemoryTool 只读
UI 显示 Memory safe summary
系统监控显示 MemoryStore Health
secret 不泄露
WriteGateway 不破坏
AI Agent 真实输入测试通过
测试通过
NEXT_STAGE_ALLOWED = true
```
