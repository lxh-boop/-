# 给 Codex 的启动 Prompt：Phase 15 ReAct Observe / Replan

你现在要继续做 Phase 15：ReAct Observe / Replan。

文档目录：

```text
D:\stock_daily_app\docs\phase15_react_observe_replan_docs
```

请先阅读：

```text
D:\stock_daily_app\docs\phase15_react_observe_replan_docs\00_总纲_Phase15_ReAct_Observe_Replan_完整执行指南.md
```

然后严格按顺序执行：

```text
1. 01_阶段A_ReAct链路审计与加载性能基线.md
2. 02_阶段B_Observation核心模型_ObservePolicy_Sanitizer.md
3. 03_阶段C_ObserveStore_ReActTrace_ReplanPolicy.md
4. 04_阶段D_Executor_ToolExecutor_Context接入Observe_Replan.md
5. 05_阶段E_AI_Agent_UI加载优化与Memory视图轻量加载.md
6. 06_阶段F_最终收敛_覆盖率_回归_交付报告.md
```

执行规则：

1. 每个阶段开始前必须先阅读对应阶段文档。
2. 每个阶段必须先输出：
   - 本阶段目标
   - 本阶段禁止事项
   - 需要检查的文件
   - 预计新增/修改文件
   - 测试命令
   - 网页功能检查计划
3. 每个阶段必须按照文档修改代码。
4. 每个阶段必须运行 compileall 和 pytest。
5. 每个阶段必须真实打开网页做功能检查，不能只依赖 pytest。
6. 每个阶段必须写阶段报告到 docs。
7. 阶段报告必须包含：
   - WEB_CHECK_DONE = true
   - WEB_CHECK_METHOD
   - WEB_CHECK_PAGES
   - WEB_CHECK_RESULT
   - WEB_CHECK_ERRORS
   - NEXT_STAGE_ALLOWED = true / false
8. 如果测试或网页检查失败，必须停止，不能进入下一阶段。
9. 只有阶段报告写明 NEXT_STAGE_ALLOWED = true，才能继续下一阶段。
10. Phase 15 主线是 ReAct Observe / Replan；AI Agent 页面加载优化和 Memory 视图轻量加载属于本阶段性能优化子任务。
11. 不要实现完整 Reflection Critic。
12. 不要实现完整 Multi-Agent Handoff。
13. 不要重写工具系统。
14. 不要重写上下文系统。
15. 不要重写 MemoryManager。
16. 不要破坏 P0 Write Gateway。
17. 不要破坏 P1-A portfolio proposal / paper trade commit 链路。
18. 不要让 LLM 或 UI 看到 confirmation_token、API key、数据库路径、内部堆栈、raw_positions、raw_evidence、raw_tool_payload 或敏感字段。
19. 不要一次性大改所有页面。
20. 旧接口必须保持兼容。
21. 每个阶段完成后只返回阶段总结，不要粘贴完整代码。


