# Phase 16-17 Reflection Critic 与 Multi-Agent Handoff 最终交付报告

生成时间：2026-07-07

## 1. 阶段范围

本阶段按 `docs/phase16_17_reflection_handoff_docs/00_总纲_Phase16_17_ReflectionCritic_MultiAgentHandoff_完整执行指南.md` 顺序完成 Phase 16 Reflection Critic 与 Phase 17 Multi-Agent Handoff。

已完成阶段：

| 阶段 | 报告 | 结果 |
| --- | --- | --- |
| Phase16-A Reflection 链路审计与 Critic 协议设计 | `docs/phase16_a_reflection_audit_report.md` | NEXT_STAGE_ALLOWED = true |
| Phase16-B Reflection 核心模型 / Policy / Sanitizer | `docs/phase16_b_critic_core_report.md` | NEXT_STAGE_ALLOWED = true |
| Phase16-C CriticEngine / Executor 只读审查接入 | `docs/phase16_c_critic_engine_integration_report.md` | NEXT_STAGE_ALLOWED = true |
| Phase16-D Reflection UI 展示与网页检查 | `docs/phase16_d_reflection_ui_web_check_report.md` | NEXT_STAGE_ALLOWED = true |
| Phase17-E Handoff 链路审计与 AgentRole 协议设计 | `docs/phase17_a_handoff_audit_report.md` | NEXT_STAGE_ALLOWED = true |
| Phase17-F Handoff 核心模型 / Router / Policy / Sanitizer | `docs/phase17_b_handoff_core_report.md` | NEXT_STAGE_ALLOWED = true |
| Phase17-G Coordinator / Specialist Handoff 运行时接入 | `docs/phase17_c_handoff_runtime_integration_report.md` | NEXT_STAGE_ALLOWED = true |
| Phase16-17-H 最终收敛 / 覆盖率 / 回归 | 本报告 | NEXT_STAGE_ALLOWED = true |

## 2. Reflection Critic 交付内容

新增/接入文件：

- `agent/reflection/critic_types.py`
- `agent/reflection/critic_policy.py`
- `agent/reflection/critic_sanitizer.py`
- `agent/reflection/critic_engine.py`
- `agent/reflection/reflection_store.py`
- `app/reflection_ui.py`
- `tests/unit/test_phase16_critic_core.py`
- `tests/unit/test_phase16_critic_policy.py`
- `tests/unit/test_phase16_critic_engine.py`
- `tests/unit/test_phase16_critic_executor_integration.py`
- `tests/unit/test_phase16_reflection_ui_safe_summary.py`

核心结果：

- `CriticAction` 已定义 7 类动作：`PASS`、`REVISE_ANSWER`、`REPLAN_READONLY`、`ASK_USER`、`REQUIRE_APPROVAL`、`BLOCK_AND_REPORT`、`HANDOFF_REQUESTED`。
- `CriticResult` 输出只包含安全摘要、问题列表、证据引用、动作建议、只读 replan hint；不包含 chain-of-thought、raw payload、token、本地路径或数据库路径。
- `AgentExecutor` 已接入 `_run_phase16_reflection`，在最终回答前执行只读审查。
- Reflection 不直接写业务状态，不调用模拟盘 commit，不绕过 WriteGateway / approval / revalidate / commit。
- AI Agent 页面和系统监控页只展示脱敏后的 Reflection 安全摘要。

## 3. Multi-Agent Handoff 交付内容

新增/接入文件：

- `agent/handoff/handoff_types.py`
- `agent/handoff/handoff_policy.py`
- `agent/handoff/handoff_sanitizer.py`
- `agent/handoff/handoff_router.py`
- `agent/handoff/handoff_coordinator.py`
- `agent/handoff/specialist_adapter.py`
- `app/handoff_ui.py`
- `tests/unit/test_phase17_handoff_core.py`
- `tests/unit/test_phase17_handoff_policy_router.py`
- `tests/unit/test_phase17_handoff_coordinator.py`
- `tests/unit/test_phase17_handoff_executor_integration.py`
- `tests/unit/test_phase17_handoff_ui_safe_summary.py`

修改接入文件：

- `agent/executor.py`
- `agent/communication/message_types.py`
- `agent/communication/message_router.py`
- `agent/context/context_types.py`
- `agent/context/context_policy.py`
- `app/pages/ai_agent.py`
- `app/pages/system_monitor.py`

核心结果：

- 新增 AgentRole：`COORDINATOR`、`PORTFOLIO_ANALYST`、`RISK_ANALYST`、`EVIDENCE_RETRIEVER`、`STRATEGY_GUARD`、`REPORT_WRITER`、`SYSTEM_DIAGNOSTIC`。
- 新增 Handoff 消息：`HANDOFF_REQUESTED`、`HANDOFF_ACCEPTED`、`HANDOFF_RESULT`、`HANDOFF_BLOCKED`。
- `HandoffCoordinator` 支持受控分派、深度限制、重复角色限制、失败隔离和结果合并。
- `SpecialistAdapter` 将现有 specialist 结果转换成结构化 `HandoffResult`，只输出摘要和引用。
- `AgentExecutor` 在只读多 Agent 协作链路和持仓审批建议链路中接入 Handoff，但不改变原有工具、模拟盘、审批和 commit 口径。
- AI Agent 页面展示 `Handoff:` caption 与安全摘要；系统监控页展示 `Handoff Health`。

## 4. 兼容性处理

最终回归中发现旧 Phase 8 测试仍要求直接加载最近 50 条会话，而 Phase 15 长对话性能优化要求默认可见窗口为 10 条。已拆分：

- `PHASE15_VISIBLE_MESSAGE_WINDOW = 10`：页面默认轻量显示。
- `PHASE8_LEGACY_DIRECT_LOAD_SIZE = 50`：旧直接加载接口兼容。

同时为 `_phase51_render_developer_details` 补回默认 `output_dir="outputs"` 与 `language="zh"`，保持旧测试和旧调用兼容。

## 5. 安全与禁止事项检查

静态 AST 扫描范围：

- `agent/reflection`
- `agent/handoff`
- `agent/specialists`

禁止写调用扫描结果：

```text
direct_write_call_hits = 0
```

结论：

- Reflection Critic 未直接调用 `execute_confirmed_plan_v2`、`paper_trade_execute`、`commit_*`、`save_positions` 等写操作。
- Handoff Coordinator / Specialist Adapter 未直接写模拟盘或策略状态。
- Specialist 输出继续通过现有 executor 汇总，不绕过 WriteGateway。
- 页面和 LLM 可见路径继续屏蔽 `confirmation_token`、API key、数据库路径、本地路径、内部堆栈、`raw_positions`、`raw_evidence`、`raw_tool_payload`。

敏感词扫描中出现的相关字段均位于 policy / sanitizer / UI redaction allowlist 或隐藏逻辑中，不是实际展示泄露。

## 6. 消息与日志追踪

最新一次真实 AI Agent 对话日志：

```text
outputs/message_logs/cht/agent_run_c9ae17639e7d.jsonl
```

最新 run 消息统计：

| message_type | count |
| --- | ---: |
| USER_REQUEST | 1 |
| CONTEXT_CREATED | 1 |
| GOAL_PARSED | 1 |
| TASK_PLANNED | 1 |
| HANDOFF_REQUESTED | 3 |
| HANDOFF_ACCEPTED | 3 |
| HANDOFF_RESULT | 3 |
| TOOL_CALL_REQUESTED | 13 |
| TOOL_RESULT_RECEIVED | 13 |
| OBSERVATION_CREATED | 14 |
| REPLAN_SKIPPED | 14 |
| ARTIFACT_CREATED | 13 |
| REFLECTION_REQUESTED | 1 |
| REFLECTION_RESULT | 1 |
| FINAL_REPORT | 1 |

全量 message log 统计：

| message_type | count |
| --- | ---: |
| FINAL_REPORT | 49 |
| HANDOFF_REQUESTED | 33 |
| HANDOFF_ACCEPTED | 33 |
| HANDOFF_RESULT | 33 |
| REFLECTION_REQUESTED | 26 |
| REFLECTION_RESULT | 26 |

Reflection 日志统计：

```text
REFLECTION_LOG_FILES = 26
PASS = 9
REPLAN_READONLY = 3
REQUIRE_APPROVAL = 14
```

最新真实 Handoff 路径：

```text
COORDINATOR -> EVIDENCE_RETRIEVER -> PORTFOLIO_ANALYST -> REPORT_WRITER
```

## 7. 测试结果

编译检查：

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
PASS
```

最终回归测试：

```text
py -3 -m pytest <phase11-17 + key multi-agent suites> -q
238 passed, 37 warnings in 125.75s
```

兼容性复测：

```text
py -3 -m pytest tests/unit/test_multi_agent_phase8_loading_performance.py tests/unit/test_phase15_agent_chat_loading.py -q
9 passed
```

最终格式修复后的快速复测：

```text
py -3 -m compileall -q app/pages/ai_agent.py
PASS

py -3 -m pytest tests/unit/test_multi_agent_phase8_loading_performance.py tests/unit/test_phase15_agent_chat_loading.py tests/unit/test_phase16_reflection_ui_safe_summary.py tests/unit/test_phase17_handoff_ui_safe_summary.py -q
16 passed in 8.43s
```

网页脚本检查：

```text
py -3 scripts/check_phase16_reflection_web.py
PASS

py -3 scripts/check_phase15_react_loading_web.py
PASS

py -3 scripts/check_phase13_communication_web.py
PASS
```

8501 健康检查：

```text
http://127.0.0.1:8501/_stcore/health -> ok
```

## 8. 真实网页检查

检查方式：

- 8501 本地 Streamlit 实例。
- 浏览器真实打开 `http://127.0.0.1:8501/`。
- 检查首页、AI Agent、AI 模拟盘、系统监控。
- AI Agent 输入真实问题，等待回答完成后检查 Handoff、Reflection、长对话加载和敏感字段。
- 系统监控页面检查 `Reflection Health`、`Handoff Health`、`ReAct Health`。

AI Agent 实测问题：

1. 查看我的当前持仓
2. 分析当前组合风险
3. 给我一个调仓建议
4. 查看最新报告
5. 查看系统状态
6. 我上次为什么建议调仓？
7. 综合分析我的当前持仓风险，并给出是否需要调仓的建议
8. 帮我检查这个调仓建议是否证据充分

网页检查结果：

```text
AI Agent answer_visible = true
Handoff summary visible = true
Reflection summary visible = true
Long chat default visible window = 10
Load earlier visible window after click = 20
System Monitor Reflection Health visible = true
System Monitor Handoff Health visible = true
System Monitor ReAct Health visible = true
Forbidden sensitive text visible = false
Page error / traceback visible = false
```

## 9. 未做事项

按阶段禁止事项，本次没有做：

- 没有训练模型。
- 没有做强化学习。
- 没有做微调。
- 没有重写 ToolExecutor / ContextManager / MessageBus / MemoryManager。
- 没有绕过 P0 WriteGateway。
- 没有绕过 P1-A portfolio proposal / paper trade commit 链路。
- 没有让 Reflection Critic 或 Handoff Specialist 直接写业务状态。

## 10. 后续建议

建议下一阶段只做小步增强：

- 为 Handoff 增加更多只读 specialist 覆盖率，例如 `RISK_ANALYST` 和 `STRATEGY_GUARD` 的真实 UI 场景验收。
- 为 Reflection 增加回答质量分层统计面板，但继续只展示脱敏摘要。
- 将 Handoff / Reflection 的统计纳入系统监控历史趋势，不改变业务执行口径。

## 11. 阶段门禁

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = `Streamlit 8501 health + Streamlit AppTest scripts + real browser checks on AI Agent and System Monitor`

WEB_CHECK_PAGES = `首页 / 预测排名, AI Agent, AI 模拟盘, 系统监控`

WEB_CHECK_RESULT = `PASS: AI Agent can answer real prompts; Handoff/Reflection summaries visible; System Monitor shows Reflection Health, Handoff Health, ReAct Health; no forbidden sensitive fields or traceback visible`

NEXT_STAGE_ALLOWED = true
