# Phase 11.1-D P1-B System Auxiliary and MCP Tool Migration Report

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## 1. Scope

本阶段只迁移系统辅助工具和 MCP 只读桥：

- `user_profile -> user.profile.get`
- `python_sandbox_analysis -> sandbox.python_analysis`
- `scheduler_status -> system.scheduler_status`
- `report / report_latest -> report.list_latest`
- 动态 `mcp.*` / `mcp_tool -> mcp.readonly.invoke`

未迁移范围：ranking、stock analysis、stock lookup、新闻 RAG、EvidenceService、PortfolioService、RiskService、模拟盘核心算法和写工具核心链路。

## 2. Before / After Status

| tool | legacy_name | legacy file | old Agent path | new canonical tool | new adapter | new service | operation_type | default Agent path |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 用户画像读取 | `user_profile` | `agent/tools/user_profile_tool.py` | legacy registry / direct helper users | `user.profile.get` | `user_profile_get_adapter` | `UserProfileService` | read | v2 `ToolExecutor` |
| Python 沙箱分析 | `python_sandbox_analysis` | `agent/tools/python_sandbox_tool.py` | `multi_task_executor` direct fallback | `sandbox.python_analysis` | `python_sandbox_analysis_adapter` | `PythonSandboxService` | system | v2 `ToolExecutor` |
| 调度状态 | `scheduler_status` | `agent/tools/scheduler_tool.py` | executor 部分 v2；multi-task 仍 fallback | `system.scheduler_status` | `scheduler_status_adapter` | `SystemAuxiliaryService` | system | v2 `ToolExecutor` |
| 最新报告列表 | `report`, `report_latest` | `agent/tools/report_tool.py` | executor 部分 v2 / legacy registry | `report.list_latest` | `report_list_latest_adapter` | `SystemAuxiliaryService` | read | v2 `ToolExecutor` |
| MCP 只读调用 | dynamic `mcp.*`, `mcp_tool` | `agent/mcp/registry_bridge.py` | `multi_task_executor` direct bridge | `mcp.readonly.invoke` | `mcp_readonly_invoke_adapter` | `McpReadOnlyClient` | read | v2 `ToolExecutor` |

## 3. Modified Files

| file | change |
| --- | --- |
| `agent/services/user_profile_service.py` | 新增用户画像只读 service，委托原 `query_user_profile()` |
| `agent/services/python_sandbox_service.py` | 新增受限 Python 沙箱 service，保留原 sandbox 安全校验 |
| `agent/services/system_auxiliary_service.py` | 新增调度状态和报告列表 service |
| `agent/services/mcp_readonly_client.py` | 新增 MCP 只读客户端，只允许 mapped/read-only MCP ToolSpec |
| `agent/tools/system_auxiliary_adapters.py` | 新增 v2 adapter，统一参数和返回格式 |
| `agent/tool_engine.py` | 注册 5 个 P1-B v2 ToolDefinition 和 legacy aliases |
| `agent/orchestration/multi_task_executor.py` | `OP_SYSTEM` 进入 v2；动态 MCP 通过 `mcp.readonly.invoke`；保留 MCP fallback 行为 |
| `agent/executor.py` | `user_profile`、`python_sandbox_analysis`、`report_latest` 单任务路径切到 v2 |
| `agent/capability_index.py` | 能力索引补充 P1-B 工具输出、动作和 agent view |
| `tests/unit/test_phase11_p1b_system_aux_tools.py` | 新增阶段 contract / regression 测试 |

## 4. Safety and Compatibility

- 旧函数全部保留，未删除页面、Pipeline 或旧测试依赖。
- `python_sandbox_analysis` 继续使用 `agent.sandbox` 的危险 import / open / file read 拦截，不允许业务状态写入。
- MCP 写工具仍禁止：`mcp.local_financial_evidence.unsafe_write_trade` 不会映射成可执行只读工具，`mcp.readonly.invoke` 会拒绝。
- MCP 动态工具仍保留原 intent / tool call 展示名，结果中增加 `v2_bridge_tool_name=mcp.readonly.invoke` 用于审计。
- MCP 失败后的本地 ranking fallback 保留；仅修正 runtime policy 传递，避免桥接后丢失 timeout/dependency/circuit 元数据。
- 写操作 approval / revalidate / idempotency 未修改，模拟盘核心算法未修改。

## 5. Static Checks

已确认这些 Agent 默认入口不再直连旧辅助函数：

```text
rg "from agent\.tools\.python_sandbox_tool|from agent\.tools\.scheduler_tool|from agent\.tools\.report_tool|execute_mcp_tool_as_tool_result\(" agent/orchestration/multi_task_executor.py agent/executor.py agent/tool_engine.py
-> no matches
```

## 6. Tests

Passed:

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
py -3 -m pytest tests\unit\test_phase11_p1b_system_aux_tools.py -q
py -3 -m pytest tests\unit\test_phase11_intent_tool_engine.py -q
py -3 -m pytest tests\unit\test_phase11_p0_write_gateway.py -q
py -3 -m pytest tests\unit\test_phase10_goal_planning.py -q
py -3 -m pytest tests\unit\test_phase10_3_capability_artifacts.py -q
py -3 -m pytest tests\unit\test_mcp_phase9_financial_evidence.py -q
```

Combined regression:

```text
py -3 -m pytest tests\unit\test_phase11_intent_tool_engine.py tests\unit\test_phase11_p0_write_gateway.py tests\unit\test_phase10_goal_planning.py tests\unit\test_phase10_3_capability_artifacts.py -q
-> 35 passed
```

MCP regression:

```text
py -3 -m pytest tests\unit\test_mcp_phase9_financial_evidence.py -q
-> 17 passed
```

Stage tests:

```text
py -3 -m pytest tests\unit\test_phase11_p1b_system_aux_tools.py -q
-> 8 passed
```

## 7. 8501 Verification

Passed:

```text
http://127.0.0.1:8501/_stcore/health -> ok
```

页面检查：

| page | result | notes |
| --- | --- | --- |
| 首页 / 预测排名 | passed | 预测排名、回测曲线、评分图、免责声明和页面导航可见；无 Streamlit exception。 |
| AI Agent | passed | 对话历史、快捷提问、工具调用折叠区和待确认计划可见；执行“查看每日自动更新和调度状态”返回调度状态；无异常框。 |
| AI 模拟盘 | passed | 用户画像、交易权限、账户摘要、资产曲线、回放、资金管理、持仓/订单模块可见；缓存加载完成；无异常框。 |
| 系统监控 | passed | 总状态、交易日期、告警数、保存监控快照、分层指标、Runtime Reliability 和历史趋势可见；无异常框。 |

Notes:

- 浏览器控制台存在 Streamlit/Vega 图表空轴 warning，不影响页面功能。
- 未点击会写业务状态的更新/回放/资金提交按钮；本阶段只做只读和页面可用性检查。

## 8. Remaining Work Not in This Stage

- P2-A MarketAnalysisService 市场分析工具收敛。
- P2-B EvidenceService 新闻 RAG 与证据工具收敛。
- P2-C PortfolioService / RiskService 抽取。
- Legacy 清理和最终 coverage artifact。

NEXT_STAGE_ALLOWED = true
