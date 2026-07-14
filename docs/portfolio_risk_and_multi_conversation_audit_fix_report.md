# Portfolio Risk And Multi Conversation Audit Fix Report

Generated at: 2026-07-07

## 1. Scope

本次只处理两个问题：

1. 纯组合风险问题，例如“分析当前的组合风险”，不能被扩展成“更稳健持仓建议 / 推荐方案 / 候选证据 / 买卖 / 调仓预览”。
2. AI Agent 页面必须显式提供多会话能力：新建会话、会话列表、切换会话、当前会话标识、删除/归档入口，并保留 Phase 15 的默认 10 条加载和 Load earlier 行为。

未修改模拟盘核心算法、WriteGateway、approval / revalidate / commit、真实交易边界、RAG 后端、模型链路和 token 配置链路。

## 2. Audit Findings

### 2.1 Portfolio Risk Root Cause

真实根因在 `agent/executor.py`：

- `rule_fallback.py` 对“分析当前的组合风险”的拆解本身是正确的，只包含 `portfolio_state` 和 `portfolio_risk`。
- 但 `Executor._normalise_readonly_multi_agent_tasks()` 原先把中文“分析”当成通用市场/个股分析触发词。
- 因此纯组合风险问题被额外加入 `ranking` / `stock_analysis` 等市场任务。
- 后续 `agent/orchestration/result_aggregator.py` 看到 `portfolio_state + portfolio_risk + ranking`，会进入“更稳健的模拟盘持仓建议”模板，导致回答越界。

### 2.2 Multi Conversation UI Root Cause

真实根因在 `app/pages/ai_agent.py`：

- 会话后端能力已经存在：`_create_conversation`、`_list_active_conversations`、`_switch_conversation`、`_delete_conversation`、`_persist_conversation_message`。
- 页面只显示旧的“当前会话 / 清空对话”，没有显式会话管理区。
- Phase 15 的消息窗口存在，但切换会话时需要重置懒加载和开发详情状态，避免跨会话污染。
- 初次修复使用 `st.expander` 后，真实浏览器没有稳定显示控件；最终改为普通 `st.container()`，真实 8501 页面已显示。

## 3. Code Changes

### 3.1 Portfolio Risk Boundary

文件：`agent/executor.py`

变更点：

- 在 `_normalise_readonly_multi_agent_tasks()` 中区分：
  - 纯组合风险分析；
  - 明确要求推荐、稳健、调仓、候选、买卖的组合建议；
  - 明确要求排名、个股、市场、新闻、RAG、证据的市场任务。
- 当问题是 `portfolio + risk` 且没有推荐/市场/个股范围时，强制关闭 `ranking`、`stock_analysis`、`stock_news`、`stock_rag` 自动扩展。
- 在只读多 Agent 协作链中，如果没有市场任务：
  - 不再调用 Market Intelligence / Evidence Retriever；
  - 只运行 Supervisor、Portfolio Analysis、Report；
  - 输出中不再塞入市场 evidence / ranking / candidate。

### 3.2 AI Agent Multi Conversation UI

文件：`app/pages/ai_agent.py`

变更点：

- 新增显式 Conversation manager 区域：
  - `New conversation / 新建对话`
  - `Delete current / 删除当前会话`
  - `Switch conversation / 切换对话`
  - `Current conversation / 当前会话标识`
  - `Conversations loaded / 已加载会话数`
- 会话列表只显示标题、更新时间和短 ID 后缀，不展示完整 conversation id。
- 新建/切换会话时重置 Phase 15/开发详情相关 session state，避免跨会话污染。
- 保留旧“清空对话”按钮作为兼容入口，但页面新增了明确的新建/切换/删除管理区。
- 将会话管理区域从 `st.expander` 改为普通容器，解决真实浏览器中控件不稳定显示的问题。

### 3.3 Tests Added / Updated

新增或更新：

- `tests/unit/test_portfolio_risk_intent_boundary.py`
- `tests/unit/test_portfolio_risk_answer_scope.py`
- `tests/unit/test_ai_agent_multi_conversation_ui.py`
- `tests/unit/test_ai_agent_new_conversation.py`
- `tests/unit/test_ai_agent_conversation_isolation.py`

覆盖点：

- 纯风险问题只调用 `portfolio_state` / `portfolio_risk`。
- 纯风险回答不包含推荐方案、候选证据、买入、卖出、调仓预览。
- 明确“更稳健 / 推荐 / 建议”的问题仍进入只读推荐链路。
- 新建会话保留旧历史、创建新 ID。
- 切换会话只加载目标会话消息，并重置 Phase 15 lazy/detail 状态。
- 删除会话只归档目标会话，不影响其他历史会话。
- UI 源码显式包含新建、删除、切换控件。

## 4. Verification

### 4.1 Commands

```powershell
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts tests\unit\test_portfolio_risk_intent_boundary.py tests\unit\test_portfolio_risk_answer_scope.py tests\unit\test_ai_agent_multi_conversation_ui.py tests\unit\test_ai_agent_new_conversation.py tests\unit\test_ai_agent_conversation_isolation.py
py -3 -m pytest tests\unit\test_portfolio_risk_intent_boundary.py tests\unit\test_portfolio_risk_answer_scope.py tests\unit\test_ai_agent_multi_conversation_ui.py tests\unit\test_ai_agent_new_conversation.py tests\unit\test_ai_agent_conversation_isolation.py -q
py -3 -m pytest tests\unit\test_phase15_agent_chat_loading.py tests\unit\test_phase16_critic_executor_integration.py tests\unit\test_phase16_reflection_ui_safe_summary.py tests\unit\test_phase17_handoff_executor_integration.py tests\unit\test_phase17_handoff_ui_safe_summary.py tests\unit\test_phase11_p0_write_gateway.py tests\unit\test_agent_write_requires_confirmation.py -q
```

### 4.2 Results

- compileall: PASS
- 新增/边界测试：`11 passed, 3 warnings`
- Phase 15/16/17 + WriteGateway 回归：`21 passed, 4 warnings`
- warnings 均为既有 `datetime.utcnow()` deprecation warning，非本次失败。

## 5. Real Web Check

8501 deployment:

- URL: `http://127.0.0.1:8501`
- Health: `ok`
- Listener: `127.0.0.1:8501`

Checked pages:

- 首页 / 预测排名
- AI Agent
- AI 模拟盘
- 系统监控

Observed result:

- 页面可打开，无 Traceback / Exception。
- AI Agent 页面显示 Conversation manager。
- 新建会话按钮可见并已用于创建测试会话。
- 切换会话下拉可展开，能看到历史会话列表。
- 实际切换到历史会话后，选中项和可见消息变化；刚创建的风险会话内容没有混入目标会话。
- 删除按钮可见；为避免破坏已有历史会话，真实页面未反复删除历史数据，删除生命周期由单测覆盖。
- Phase 15 `Showing the latest 10 messages` 和 `Load earlier messages` 仍可见。

Risk query E2E check:

- Query: `分析当前的组合风险`
- Latest run: `agent_run_00541fad20e3`
- DB trace tools: `portfolio_state`, `portfolio_risk`
- Latest answer heading: `当前模拟盘组合风险分析`
- Latest answer contains risk metrics/warnings.
- Latest answer does not contain:
  - `更稳健的模拟盘持仓建议`
  - `推荐方案`
  - `候选证据`
  - `买入`
  - `卖出`
  - `调仓建议`

## 6. Final Flags

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = real browser on `http://127.0.0.1:8501` + read-only DB trace + pytest

WEB_CHECK_PAGES = 首页 / 预测排名, AI Agent, AI 模拟盘, 系统监控

WEB_CHECK_RESULT = PASS

PORTFOLIO_RISK_PURE_READONLY = true

PORTFOLIO_RISK_ALLOWED_TOOLS = portfolio_state, portfolio_risk

PORTFOLIO_RISK_MARKET_EXPANSION_BLOCKED = true

RECOMMENDATION_PATH_STILL_AVAILABLE = true

MULTI_CONVERSATION_UI_VISIBLE = true

CONVERSATION_SWITCH_CHECKED = true

CONVERSATION_ISOLATION_CHECKED = true

DELETE_ARCHIVE_UNIT_CHECKED = true

TRACEBACK_ERROR = false

NEXT_STAGE_ALLOWED = true

