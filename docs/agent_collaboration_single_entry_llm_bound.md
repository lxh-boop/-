# Agent 单一入口与 Run 级统一 LLMService 改造

## 1. 基线

本代码基于用户提供的源码快照构建：

- `stock_daily_app_agent_context_20260721_194842.zip`
- ZIP SHA-256：`cfd71a3f61e4aed6e1801929d2b31bb66bb54dca2895cdd2247b24febf042a94`
- 原始 `agent/executor.py`：5231 行

原始 Executor 中已经完成以下关键改造，本包全部保留：

1. 每次 `run_agent_request()` 只解析一次当前模型配置；
2. 只创建一个 `LLMService(settings=active_llm)`；
3. 使用 `register_llm_execution_dependencies()` 绑定到本次 `run_id`；
4. Planner、Completion、Reporter、Critic 复用同一服务；
5. Profile、Adapter、response contract、JSON repair、审计由 `core/llm/` 统一管理。

## 2. 修改目标

将自然语言 Agent 请求统一为：

```text
app/pages/ai_agent.py
→ agent.executor.run_agent_request
→ execute_unified_agent_request（只调用一次）
→ MainEntryDecisionPlanner
→ CoordinatorPlanner（Agent 级 DAG）
→ 专业 Agent
→ 专业 Agent 私有能力规划
→ 标准 AgentResult
→ Report Writer / Executor Final Report
```

确认和拒绝：

```text
Main Coordinator / AI Agent pending card
→ ControlGateway
→ WriteGateway
→ Approval / token / plan_hash / expiry
→ Revalidate
→ Commit
```

## 3. 单一 LLMService

新协作层不接受并重新解析：

```text
llm_api_key
llm_base_url
llm_model
```

它只接受 Executor 已创建的：

```python
llm_service: LLMService
```

传递链：

```text
Executor LLMService（对象 A）
├─ MainEntryDecisionPlanner（对象 A）
├─ CoordinatorPlanner（对象 A）
├─ RequirementEngine（对象 A）
├─ SpecialistRuntime（对象 A）
├─ ScopedBusinessToolRuntime（对象 A）
├─ Strategy Guard（对象 A）
└─ CoordinatorReporter / Report Writer（对象 A）
```

`agent/collaboration_v2/llm_runtime.py` 只允许：

1. 使用显式传入的服务；
2. 或按 `run_id` 从 `core.llm.dependencies` 取回同一对象；
3. 若两个对象身份不一致，立即失败；
4. 不得调用 `resolve_active_llm_settings()`；
5. 不得创建第二个 `LLMService` 或 `LLMClient`。

## 4. 旧入口处理

### 完全退出主链

- `agent/executor.py` 不再导入或调用旧 `route_agent_query()`；
- 删除 Executor 内语言 fast path 和全部旧 Intent 分发主块；
- `agent/router.py` 不再调用 `decompose_intent()` 或 `extract_parameters()`；
- `agent/intent_router.py` 不再执行关键词匹配；
- `agent/agent_registry.py` 不再根据关键词选择旧 Agent；
- `agent/agent_core.py` 不再使用旧 `route_intent()`；
- AI Agent 页面不再直接调用 `execute_confirmed_plan_v2()` 或 `reject_confirmation_plan()`。

### 兼容门面

历史公开函数名可以继续被旧代码导入，但只能委托：

```text
route_agent_query     → route_unified_agent_request
route_intent          → 固定返回 agent_collaboration_v2
answer_with_registry  → run_agent_request
agent_core.run_agent  → run_agent_request
```

它们不再具备第二套业务语义判断能力，因此不会出现新旧入口同时命中。

## 5. Main Agent 与专业 Agent 边界

Main Coordinator 只能看到：

- 用户请求；
- 会话摘要；
- Agent Capability Cards；
- 标准 AgentTask；
- 标准 AgentResult；
- 非敏感审批状态摘要。

Main Coordinator 看不到：

- Tool 名称；
- Tool Schema；
- 参数 Schema；
- 数据库表；
- SQL；
- 本地路径；
- 原始 Tool payload；
- confirmation token；
- 专业 Agent 私有内部计划。

专业 Agent 收到 AgentTask 后，使用同一 `LLMService` 在私有能力目录中选择最少能力。内部调用明细不返回 Main Coordinator，只返回调用数量和标准结论。

## 6. Proposal 与 Commit

Strategy Guard：

1. 只读取 `ToolRegistry` 中 `operation_type=proposal` 且允许 `AGENT_MAIN` 的能力；
2. 私有 LLM 只可选择一个 Proposal 能力；
3. 调用时固定 `approval_granted=False`；
4. 不导入旧 Router；
5. 不调用 Commit；
6. 返回 `PROPOSAL_READY`、`plan_id`、`proposal_id` 和 `requires_approval`。

Commit 仍由现有安全链完成：

```text
ControlGateway
→ execute_confirmed_plan_v2
→ ToolExecutor(write, approval_granted=True)
→ 原 token / plan_hash / expiry / business-state revalidation
→ idempotent Commit
```

本包不修改 `agent/write_gateway.py`、`agent/tool_engine.py` 和原业务 commit service。

## 7. Shared Session Memory

`SessionMemoryStore` 使用 SQLite：

```text
outputs/session_memory/session_memory.sqlite
```

特性：

- session 隔离；
- 默认 24 小时 TTL；
- 版本化更新；
- 用户确认事实优先；
- 冲突写入保护；
- 访问日志；
- waiting task 持久化；
- 澄清答案恢复原任务；
- 只注入任务相关摘要，不注入完整记忆。

## 8. NEED_CONTEXT

专业 Agent 按顺序检查：

```text
AgentTask 输入
→ Session Memory exact get
→ Session Memory search
→ dependency AgentResult
→ 自身私有业务能力
```

仍缺失才返回统一 `NEED_CONTEXT`。

Main Coordinator 最多进行两轮恢复。恢复 Agent 由同一个 `LLMService` 根据能力卡选择，不再使用关键词映射。无法恢复时只向用户提出一次合并问题。

## 9. 文件

### 新增

```text
agent/collaboration_v2/
  __init__.py
  agent_directory.py
  context_service.py
  control_gateway.py
  coordinator.py
  entry_decision.py
  integration.py
  llm_runtime.py
  models.py
  planner.py
  requirements.py
  session_memory.py
  specialist_runtime.py
  tool_runtime.py
```

### 完整替换

```text
agent/executor.py
agent/router.py
agent/agent_core.py
agent/agent_registry.py
agent/intent_router.py
app/pages/ai_agent.py
```

### 专项测试

```text
tests/unit/test_agent_collaboration_v2_control_gateway.py
tests/unit/test_agent_collaboration_v2_memory.py
tests/unit/test_agent_collaboration_v2_models.py
tests/unit/test_agent_collaboration_v2_runtime.py
tests/unit/test_agent_collaboration_v2_single_entry_static.py
```

## 10. 安装

Git Bash：

```bash
bash install_agent_collaboration_single_entry.sh "D:/stock_daily_app"
```

WSL：

```bash
bash install_agent_collaboration_single_entry.sh "/mnt/d/stock_daily_app"
```

安装器：

- 不创建代码备份；
- 删除旧安装器遗留的 `.agent_collaboration_v2_backup`；
- 先验证 payload；
- 检查当前项目是否具备 Run 级 `LLMService` 基础；
- 完整替换目标文件；
- 运行静态边界验证；
- 运行 Python 编译；
- 安装了 pytest 时运行专项测试。

## 11. Git 回滚

```bash
bash rollback_agent_collaboration_single_entry.sh "D:/stock_daily_app"
```

脚本只使用 Git 恢复，不读取任何安装备份。

## 12. 验收标准

1. Executor 中 `execute_unified_agent_request()` 调用次数必须等于 1；
2. Executor 不得导入或调用旧 Router；
3. 新协作层不得实例化 `LLMClient` 或 `LLMService`；
4. 所有 Agent 阶段的 `profile_id/config_hash` 与 Executor 一致；
5. 旧 Router、Registry、Intent Router、Agent Core 只能委托；
6. AI Agent 确认与拒绝卡片只能调用 `execute_control_action()`；
7. Main Coordinator 返回的 `tool_calls` 必须为空；
8. Strategy Guard 只能调用 `OP_PROPOSAL`，且 `approval_granted=False`；
9. Commit 仍需原 WriteGateway 确认和重新校验；
10. 不重新引入 `final_action/watchlist/down_weight` 等已废弃字段；
11. 专项测试全部通过。
