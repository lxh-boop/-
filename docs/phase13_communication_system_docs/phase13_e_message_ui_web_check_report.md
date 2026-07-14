# Phase 13-E Message Trace UI Web Check Report

## Scope

- 接入 AI Agent 页面 Message Trace 安全摘要展示。
- 接入系统监控页 MessageBus Health 只读健康摘要。
- 保持旧页面入口、旧会话、P0 Write Gateway、P1-A proposal / commit 链路兼容。
- 不展示 raw payload、confirmation_token、API key、数据库路径或内部堆栈。

## Changes

- `app/pages/ai_agent.py`
  - 新增 `_build_message_trace_safe_summary()` 与 `_format_message_trace_caption()`。
  - `_render_result_details()` 增加 `Message Trace 安全摘要` 折叠展示。
  - UI 展示使用 `_redact_ui_payload_for_display()` 移除敏感字段名和值。
  - 修复本阶段中发现的 AI Agent 页面编码损坏，恢复为 UTF-8 可读中文。
- `app/pages/system_monitor.py`
  - 新增 MessageBus Health 区块。
  - 只显示 message log 相对安全摘要，不显示本地绝对路径。
- `scripts/check_phase13_communication_web.py`
  - 增加四个页面 AppTest 检查。
- `tests/unit/test_phase13_message_ui_safe_trace.py`
  - 覆盖 Message Trace 安全摘要、无 run_id、敏感字段过滤。

## Test Commands

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts`
- `py -3 -m pytest tests/unit/test_phase13_message_ui_safe_trace.py tests/unit/test_phase12_context_ui_safe_summary.py -q`
- `py -3 -m pytest tests/unit/test_phase13_message_executor_integration.py tests/unit/test_phase13_message_tool_executor_integration.py tests/unit/test_phase13_message_write_gateway_integration.py tests/unit/test_phase13_message_policy.py tests/unit/test_phase13_message_store_bus.py tests/unit/test_phase13_message_router_trace.py -q`
- `py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py tests/unit/test_agent_write_requires_confirmation.py tests/unit/test_agent_action_proposal_gateway.py -q`
- `py -3 scripts/check_phase13_communication_web.py`

## Test Results

- compileall: PASS
- Phase 13 UI safe trace + Phase 12 UI safe summary: PASS, 8 passed
- Phase 13 executor / tool / write gateway / policy / store / router regression: PASS, 12 passed
- P0 write gateway and approval regression: PASS, 10 passed
- `scripts/check_phase13_communication_web.py`: PASS
  - 首页 / 预测排名: exceptions=0, errors=0
  - AI Agent: exceptions=0, errors=0
  - AI 模拟盘: exceptions=0, errors=0
  - 系统监控: exceptions=0, errors=0
- Note: 系统监控页仍有 Streamlit dataframe Arrow 自动修复 warning，页面无异常，属于既有非阻塞类型兼容提示。

## Web Check

- WEB_CHECK_DONE = true
- WEB_CHECK_METHOD = Streamlit health + Streamlit AppTest + local Playwright Chromium real-page navigation
- WEB_CHECK_PAGES = 首页 / 预测排名, AI Agent, AI 模拟盘, 系统监控
- WEB_CHECK_RESULT = PASS
  - `http://127.0.0.1:8501/_stcore/health` returned `ok`
  - Playwright Chromium opened real 8501 page and navigated 首页 / AI 模拟盘 / AI Agent / 系统监控.
  - No visible Traceback / ModuleNotFoundError / NameError / SyntaxError.
  - No visible mojibake or `????`.
  - No visible `confirmation_token`, `api_key`, `tushare_token`, `agent_quant.db`.
  - Clean AppTest user submitted `查看每日自动更新和调度状态`; response rendered and `Message trace: messages=8 | last=FINAL_REPORT | tools=1 | errors=0` was visible.

## Compatibility

- No MessageBus write authority was added.
- No UI path exposes raw confirmation token or local DB path.
- Existing old result expanders remain available but use display redaction.
- Existing conversation repository writes remain unchanged except metadata redaction.

## Decision

NEXT_STAGE_ALLOWED = true
