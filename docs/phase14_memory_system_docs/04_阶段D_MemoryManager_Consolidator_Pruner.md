# Phase 14-D：MemoryManager、Consolidator、Pruner

## 本阶段目标

建立记忆管理层，负责写入、检索、整合和遗忘。

必须实现：

```text
MemoryManager
MemoryCandidateExtractor
MemoryConsolidator
MemoryPruner
```

MemoryManager 必须支持：

```text
remember()
remember_candidate()
retrieve()
retrieve_for_context()
forget()
consolidate()
prune()
```

## 允许做

```text
新增 MemoryManager
新增 MemoryCandidateExtractor
新增 MemoryConsolidator
新增 MemoryPruner
接入 MessageTrace / Artifact / Context 的离线提取接口
新增测试
```

## 禁止做

```text
不直接改 executor 主链
不改 ToolExecutor / WriteGateway
不改业务算法
不让 MemoryManager 直接 commit
不让 LLM 直接决定长期写入
不实现 Reflection Critic
不实现 ReAct
```

## 建议新增/修改文件

```text
agent/memory/memory_manager.py
agent/memory/memory_candidate_extractor.py
agent/memory/memory_consolidator.py
agent/memory/memory_pruner.py
tests/unit/test_phase14_memory_manager.py
tests/unit/test_phase14_memory_consolidator_pruner.py
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
py -3 -m pytest tests/unit/test_phase14_memory_manager.py -q
py -3 -m pytest tests/unit/test_phase14_memory_consolidator_pruner.py -q
py -3 -m pytest tests/unit/test_phase14_memory_store_retriever.py -q
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
docs/phase14_d_memory_manager_report.md
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
MemoryManager 完成
CandidateExtractor 完成
Consolidator 完成
Pruner 完成
写入前 policy 检查
写入前 storage sanitization
检索安全视图
secret 不保存
测试通过
网页检查通过
NEXT_STAGE_ALLOWED = true
```
