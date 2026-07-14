# Phase 14：MemoryManager 记忆系统完整执行指南

## 当前项目基础

当前项目已经完成三层 Agent Runtime 底座：

```text
Phase 11：工具系统
ToolDefinition / ToolExecutor / ToolAdapter / DomainService / UnifiedToolResult / WriteGateway

Phase 12：上下文系统
ContextManager / ContextBundle / ContextPolicy / ContextSanitizer / ContextStore / ContextResolver

Phase 13：通信系统
AgentMessage / MessageBus / MessageStore / MessageRouter / MessageTrace
```

Phase 14 的目标是建立 **MemoryManager 记忆系统**。它不替代工具系统、上下文系统和通信系统，而是在它们之上解决：

```text
什么信息值得长期记住？
什么时候取出来？
怎么避免记错？
怎么避免低价值历史污染？
怎么避免敏感信息进入长期记忆？
怎么支持后续 ReAct、Reflection 和 Multi-Agent？
```

## 参考图中的结构如何落地

用户提供的图中包含：

```text
前端层：SimpleAgent / ToolRegistry / MemoryTool / RAGTool
管理层：MemoryManager / RAGPipeline
记忆类型层：WorkingMemory / EpisodicMemory / SemanticMemory / PerceptualMemory
RAG处理层：DocumentProcessor / 智能问答引擎
存储抽象层：SQLiteDocumentStore / Neo4jGraphStore / QdrantVectorStore
基础设施层：SQLite / Neo4j / Qdrant / EmbeddingService
```

本项目按金融 Agent 实际情况落地为：

```text
必做：
MemoryManager
MemoryTool
WorkingMemory
EpisodicMemory
SemanticMemory
EvidenceMemory
PortfolioMemory
ReflectionMemory 轻量占位
PerceptualMemory 轻量占位
SQLiteMemoryStore
MemoryPolicy
MemorySanitizer
MemoryRetriever
MemoryConsolidator
MemoryPruner
MemoryContextBridge

预留：
GraphMemoryStore 接口，占位 Neo4jGraphStore
VectorMemoryStore 接口，占位 QdrantVectorStore
EmbeddingService 复用现有 RAG / Evidence 能力
```

## 为什么不直接强制 Neo4j / Qdrant

```text
1. 当前项目是本地金融模拟盘，不是大规模开放知识图谱系统。
2. SQLite 足够承载用户偏好、历史建议、执行事件、风险摘要和证据摘要。
3. 现有 RAG / EvidenceService 已经具备文本证据检索能力。
4. 强制引入 Neo4j/Qdrant 会增加部署、测试和维护复杂度。
5. 先做接口抽象，后续需要再替换存储层。
```

阶段策略：

```text
先 SQLite
再接口抽象
后续再接 Graph / Vector
先文本和结构化记忆
后续再做多模态记忆
```

## 目标目录

```text
agent/memory/
    __init__.py
    memory_types.py
    memory_policy.py
    memory_sanitizer.py
    memory_importance.py
    working_memory.py
    memory_store.py
    graph_memory_store.py
    vector_memory_store.py
    memory_retriever.py
    memory_candidate_extractor.py
    memory_consolidator.py
    memory_pruner.py
    memory_context_bridge.py
    memory_manager.py
    memory_tool.py
```

## 总体执行链路

```text
User Input
→ ContextManager 创建 ContextBundle
→ MessageBus 记录 USER_REQUEST
→ MemoryManager.retrieve_for_context()
→ MemoryContext 写入 memory_refs / memory_summary
→ Planner / ToolExecutor 使用 MemoryContext
→ 工具执行产生 UnifiedToolResult
→ ArtifactStore 保存结果
→ MessageTrace 记录执行过程
→ MemoryCandidateExtractor 提取候选记忆
→ MemoryPolicy 判断是否值得保存
→ MemorySanitizer 脱敏
→ SQLiteMemoryStore 保存
→ MemoryConsolidator 周期性整合
→ MemoryPruner 过期、遗忘、冲突处理
```

## 严格禁止

```text
不重写工具系统
不重写上下文系统
不重写通信系统
不实现完整 ReAct
不实现完整 Reflection
不实现完整 Multi-Agent Handoff
不改变模拟盘核心算法
不改变 WriteGateway 审批链路
不让 MemoryManager 直接 commit 写业务状态
不把 confirmation_token 写入长期记忆
不把 API key / DB path / 本地路径 / 内部堆栈写入长期记忆
不强制引入 Neo4j / Qdrant / Redis
不把所有对话无差别写入记忆
不让 LLM 直接决定长期写入，必须经过 MemoryPolicy
```

## 阶段顺序

```text
1. 01_阶段A_记忆来源审计与目标设计.md
2. 02_阶段B_Memory核心模型_Policy_Sanitizer.md
3. 03_阶段C_WorkingMemory_SQLiteMemoryStore_Retriever.md
4. 04_阶段D_MemoryManager_Consolidator_Pruner.md
5. 05_阶段E_Context_Message_Tool_UI接入.md
6. 06_阶段F_最终收敛_覆盖率_回归_交付报告.md
```


## 统一执行规则

每个阶段必须：

```text
1. 先阅读本阶段文档
2. 输出本阶段目标、禁止事项、检查文件、预计新增/修改文件、测试命令、网页检查计划
3. 检查当前代码
4. 修改代码
5. 运行 compileall
6. 运行 pytest
7. 启动或检查 8501
8. 真实打开网页检查：首页 / 预测排名、AI Agent、AI 模拟盘、系统监控
9. 实际输入 AI Agent 问题
10. 写阶段报告
11. 报告中写 WEB_CHECK_DONE = true
12. 报告中写 NEXT_STAGE_ALLOWED = true 后才能进入下一阶段
```

如果测试或网页检查失败：

```text
立即停止
不得进入下一阶段
阶段报告写 NEXT_STAGE_ALLOWED = false
```


## 最终验收标准

```text
MemoryManager 完成
MemoryTool 完成
WorkingMemory 完成
EpisodicMemory 完成
SemanticMemory 完成
EvidenceMemory 完成
PortfolioMemory 完成
ReflectionMemory 轻量占位完成
PerceptualMemory 轻量占位完成
SQLiteMemoryStore 完成
GraphMemoryStore 接口占位完成
VectorMemoryStore 接口占位完成
MemoryPolicy 完成
MemorySanitizer 完成
MemoryRetriever 完成
MemoryConsolidator 完成
MemoryPruner 完成
MemoryContextBridge 接入 ContextManager
MessageTrace 可生成 EpisodicMemory candidate
Artifact 可生成 Evidence/Portfolio memory candidate
MemoryTool 只读
secret 不泄露
MemoryManager 不写业务状态
WriteGateway 不破坏
页面真实检查通过
全部测试通过
8501 health ok
最终报告生成
```
