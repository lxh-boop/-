# Phase 14-B：Memory 核心模型、Policy、Sanitizer

## 本阶段目标

建立记忆系统核心数据结构和安全策略，但暂不接入主执行链。

必须实现：

```text
MemoryRecord
MemoryType
MemoryScope
MemoryVisibility
MemoryPolicy
MemorySanitizer
MemoryImportanceScorer
```

MemoryType 至少包括：

```text
WORKING
EPISODIC
SEMANTIC
EVIDENCE
PORTFOLIO
REFLECTION
PERCEPTUAL
```

## 允许做

```text
新增 agent/memory/
新增 memory 数据模型
新增 MemoryPolicy
新增 MemorySanitizer
新增 MemoryImportanceScorer
新增基础单元测试
保持旧接口兼容
```

## 禁止做

```text
不接入 executor 主链
不改 ToolExecutor / ContextManager / MessageBus / WriteGateway
不改 UI
不实现 ReAct / Reflection / Multi-Agent
不强制外部服务
```

## 建议新增/修改文件

```text
agent/memory/__init__.py
agent/memory/memory_types.py
agent/memory/memory_policy.py
agent/memory/memory_sanitizer.py
agent/memory/memory_importance.py
tests/unit/test_phase14_memory_core.py
tests/unit/test_phase14_memory_policy.py
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
py -3 -m pytest tests/unit/test_phase14_memory_core.py -q
py -3 -m pytest tests/unit/test_phase14_memory_policy.py -q
py -3 -m pytest tests/unit/test_phase12_context_policy.py -q
py -3 -m pytest tests/unit/test_phase13_message_policy.py -q
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
docs/phase14_b_memory_core_report.md
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
agent/memory 包建立
MemoryRecord 建立
MemoryType 建立
MemoryPolicy 建立
MemorySanitizer 建立
MemoryImportanceScorer 建立
secret 不可保存
大对象 summary + ref
compileall 通过
单测通过
真实网页检查通过
NEXT_STAGE_ALLOWED = true
```
