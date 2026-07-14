# Phase 12：完整 ContextManager 上下文系统执行总纲

## 一、当前项目状态

当前项目已经完成或正在完成：

```text
Phase 11 工具系统工程化
ToolDefinition
ToolAdapter
ToolExecutor
UnifiedToolResult
Artifact / audit
Write Gateway
P0 写操作闭环
P1-A 组合建议 / 调仓预案工具 v2 化
```

工具系统解决的是：

```text
Agent 可以调用什么工具
工具怎么注册
工具怎么执行
工具结果怎么返回
写操作怎么审批
```

现在要做的是 **完整上下文系统**，解决：

```text
Agent 每一步到底应该知道什么？
上下文从哪里来？
哪些上下文可以给 LLM？
哪些上下文只能给工具？
上一轮结果怎么继承？
Artifact 怎么引用和复用？
上下文如何裁剪？
网页页面怎么确保不被重构破坏？
```

---

## 二、Codex 执行方式

你必须按以下顺序执行文档：

```text
1. 01_阶段A_上下文来源审计与目标设计.md
2. 02_阶段B_Context核心模型_Policy_Sanitizer_Window.md
3. 03_阶段C_ContextStore_Resolver_Artifact_Approval集成.md
4. 04_阶段D_Executor_ToolExecutor_UserGoal_TaskPlan接入.md
5. 05_阶段E_UI接入与真实网页功能检查.md
6. 06_阶段F_最终收敛_覆盖率_回归_交付报告.md
```

每个阶段必须：

```text
先阅读阶段文档
→ 输出本阶段修改范围和禁止事项
→ 检查当前代码
→ 修改代码
→ 运行 compileall
→ 运行本阶段 pytest
→ 运行必要回归 pytest
→ 启动或检查 8501
→ 真实打开网页做功能检查
→ 写阶段迁移报告
→ 报告中写 NEXT_STAGE_ALLOWED = true
→ 才能进入下一阶段
```

如果任何阶段失败：

```text
立即停止
不要进入下一阶段
修复当前阶段失败
阶段报告写 NEXT_STAGE_ALLOWED = false
```

---

## 三、真实网页检查是强制要求

每个阶段都不能只跑 pytest。

必须真实检查页面：

```text
http://127.0.0.1:8501/_stcore/health
首页
AI Agent 页面
AI 模拟盘页面
系统监控页面
报告页面 / 最新报告入口，如存在
```

如果项目有浏览器自动化能力，优先使用 Playwright 或 Selenium。

如果没有浏览器自动化能力，必须：

```text
启动 Streamlit
打开页面
记录页面是否出现 Traceback / ModuleNotFoundError / NameError / KeyError
记录关键功能是否可见
记录测试输入和输出摘要
把检查结果写入阶段报告
```

每阶段报告必须包含：

```text
WEB_CHECK_DONE = true
WEB_CHECK_METHOD = playwright / selenium / manual / health+manual
WEB_CHECK_PAGES = [...]
WEB_CHECK_RESULT = pass / fail
WEB_CHECK_ERRORS = [...]
```

如果没有真实网页检查，不允许写：

```text
NEXT_STAGE_ALLOWED = true
```

---

## 四、完整上下文系统最终目标

最终架构：

```text
User Input
→ ContextManager.create_initial_context()
→ ContextBundle
→ UserGoal Parser
→ TaskPlanner
→ ContextManager.build_tool_context()
→ ToolExecutor
→ ContextManager.update_from_tool_result()
→ ArtifactContext / RuntimeContext
→ ContextManager.build_report_context()
→ Report Generator
```

最终上下文分层：

```text
ContextBundle
├── UserContext
├── ConversationContext
├── TaskContext
├── ToolContext
├── PortfolioContext
├── EvidenceContext
├── ArtifactContext
├── ApprovalContext
├── RuntimeContext
└── MemoryContext 轻量占位
```

注意：

```text
本阶段是完整上下文系统
但不是完整 MemoryManager
也不是完整 MessageBus
也不是多 Agent Handoff
```

MemoryContext 只保留接口和引用，不实现长期记忆、embedding memory、自动记忆写入。

---

## 五、统一安全原则

必须保证：

```text
LLM 不可见 confirmation_token 原文
LLM 不可见 API key
LLM 不可见数据库连接信息
LLM 不可见内部堆栈
LLM 不可见敏感文件路径
LLM 只看 portfolio/evidence 摘要和 artifact refs
工具可按权限读取完整结构化 artifact
UI 只显示 safe fields
Audit 可以记录内部 trace，但不得泄露 secret
```

---

## 六、不得破坏现有功能

整个 Phase 12 必须保持：

```text
P0 写入口闭环不破坏
P1-A 调仓 proposal / commit 不破坏
AI Agent 页面不报错
AI 模拟盘页面不报错
首页不报错
系统监控不报错
旧调用不传 ContextBundle 时仍可 minimal context 兼容
```

---

## 七、每阶段统一测试底线

每阶段至少运行：

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py -q
py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py -q
py -3 -m pytest tests/unit/test_phase10_goal_planning.py -q
py -3 -m pytest tests/unit/test_phase10_3_capability_artifacts.py -q
```

涉及写操作或审批时，还必须运行：

```text
py -3 -m pytest tests/unit/test_agent_write_requires_confirmation.py -q
py -3 -m pytest tests/unit/test_agent_action_proposal_gateway.py -q
py -3 -m pytest tests/unit/test_multi_agent_phase3_human_approval.py -q
```

如果项目存在 P1-A/P1-B/P2 工具重构测试，也必须运行对应测试。

---

## 八、每阶段迁移报告要求

每阶段必须生成：

```text
docs/phase12_<阶段名>_context_report.md
```

报告必须包含：

```text
阶段目标
修改前状态表
修改文件
新增/修改模块
安全策略
兼容策略
测试命令与结果
真实网页检查方法
真实网页检查页面
真实网页检查结果
失败项
未完成项
NEXT_STAGE_ALLOWED = true / false
```

---

## 九、最终完成标准

所有阶段完成后，必须满足：

1. ContextManager 建立；
2. ContextBundle 建立；
3. UserContext / ConversationContext / TaskContext / ToolContext / PortfolioContext / EvidenceContext / ArtifactContext / ApprovalContext / RuntimeContext 建立；
4. MemoryContext 轻量占位建立；
5. ContextPolicy 建立；
6. ContextSanitizer 建立；
7. ContextWindow 裁剪建立；
8. ContextStore 建立；
9. ContextResolver 建立；
10. ToolExecutor 可接收 ToolContext；
11. UserGoal / TaskPlan 可读取 ContextBundle；
12. Artifact 可进入 ArtifactContext；
13. Approval 可进入 ApprovalContext；
14. pending plan 不泄露 token；
15. 大对象不直接进入 prompt；
16. 旧接口 minimal context 兼容；
17. 页面真实检查通过；
18. 全量回归通过；
19. 8501 health ok；
20. 输出最终上下文系统交付报告。

---

## 十、所有阶段完成后回复格式

只返回：

1. 各阶段是否通过；
2. 新增 Context 模块清单；
3. 接入点清单；
4. 安全过滤结果；
5. 真实网页检查结果；
6. 测试结果；
7. 仍保留的兼容入口；
8. 当前不做 MemoryManager / MessageBus 的说明；
9. 下一阶段建议。

不要粘贴完整代码。
