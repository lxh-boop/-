# Phase 14-C：WorkingMemory、SQLiteMemoryStore、MemoryRetriever

## 本阶段目标

建立记忆存储与检索基础设施。

必须实现：

```text
WorkingMemory：内存 + TTL
SQLiteMemoryStore：结构化长期记忆
MemoryRetriever：按类型、标签、实体、时间、重要性检索
GraphMemoryStore：接口占位
VectorMemoryStore：接口占位
```

SQLite 建议路径：

```text
outputs/memory/memory_store.sqlite
```

## 允许做

```text
新增 WorkingMemory
新增 SQLiteMemoryStore
新增 MemoryRetriever
新增 GraphMemoryStore 接口占位
新增 VectorMemoryStore 接口占位
新增测试
不强制安装 Neo4j/Qdrant
```

## 禁止做

```text
不强制引入 Neo4j / Qdrant / Redis
不改业务数据库核心表
不让 MemoryStore 写模拟盘状态
不存 secret
不接入主链
```

## 建议新增/修改文件

```text
agent/memory/working_memory.py
agent/memory/memory_store.py
agent/memory/memory_retriever.py
agent/memory/graph_memory_store.py
agent/memory/vector_memory_store.py
tests/unit/test_phase14_working_memory.py
tests/unit/test_phase14_memory_store_retriever.py
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
py -3 -m pytest tests/unit/test_phase14_working_memory.py -q
py -3 -m pytest tests/unit/test_phase14_memory_store_retriever.py -q
py -3 -m pytest tests/unit/test_phase14_memory_core.py -q
py -3 -m pytest tests/unit/test_phase14_memory_policy.py -q
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
docs/phase14_c_memory_store_retriever_report.md
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
WorkingMemory 完成
SQLiteMemoryStore 完成
MemoryRetriever 完成
GraphMemoryStore 接口占位
VectorMemoryStore 接口占位
secret 不落盘
检索可用
测试通过
真实网页检查通过
NEXT_STAGE_ALLOWED = true
```
