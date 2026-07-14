# Phase 12-E Context UI Web Check Report

## Scope

- Added a minimal AI Agent UI integration for Phase 12 context visibility.
- Added a safe context summary helper and a visible compact caption for `context_id`, `run_id`, `trace_id`, task count, artifact count, and pending approval status.
- Kept the full context JSON in a folded `Context 安全摘要` expander.
- Changed AI Agent technical JSON rendering to use existing UI redaction.
- Changed pending-plan technical details and confirmation result JSON to use redacted payloads.
- Added `scripts/check_phase12_context_web.py` as a health/checklist helper.

## Prohibitions Checked

- Did not rewrite the tool system.
- Did not change P0 Write Gateway execution.
- Did not change P1-A proposal or paper-trade commit behavior.
- Did not add MemoryManager or MessageBus.
- Did not display raw `confirmation_token`, API key, database path, or stack traces.
- Did not change AI paper-trading business algorithms.

## Files Changed

- `app/pages/ai_agent.py`
- `scripts/check_phase12_context_web.py`
- `tests/unit/test_phase12_context_ui_safe_summary.py`

## Context Summary Fields

- `context_available`
- `context_id`
- `run_id`
- `trace_id`
- `current_task_count`
- `artifact_ref_count`
- `artifact_refs` with safe `artifact_id` and `artifact_type`
- `pending_approval_exists`
- `pending_approval.plan_id`
- `pending_approval.status`
- `pending_approval.requires_user_confirmation`
- `context_warning_count`
- `safety.secrets_redacted`
- `safety.large_objects_hidden`
- `safety.raw_paths_hidden`

Visible caption format:

```text
Context safe summary: context_id=<tail> | run_id=<tail> | trace_id=<tail> | tasks=<n> | artifacts=<n> | pending_approval=<yes/no>
```

## Safety Filtering Result

- `confirmation_token` and `confirmation_token_hash` are removed or redacted.
- API key and Tushare token keys are redacted.
- `db_path`, `database_path`, local Windows paths, and `agent_quant.db` are redacted.
- Internal stack traces are replaced with `[redacted internal stack]`.
- `token_estimate` and context token metrics remain visible because they are non-secret operational metrics.
- Pending plans display `_technical_plan_details(plan)` instead of raw plan JSON.

## Test Results

```text
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
PASS

py -3 -m pytest tests/unit/test_phase12_context_ui_safe_summary.py -q
4 passed

py -3 -m pytest tests/unit/test_phase12_context_executor_integration.py -q
2 passed

py -3 -m pytest tests/unit/test_phase12_context_tool_executor.py -q
2 passed

py -3 -m pytest tests/unit/test_phase12_context_policy.py -q
4 passed

py -3 -m pytest tests/unit/test_phase11_p0_write_gateway.py tests/unit/test_agent_write_requires_confirmation.py -q
7 passed

Combined rerun after caption update:
19 passed
```

Known warning: existing `datetime.utcnow()` deprecation in `agent/capability_index.py`; not introduced by Phase 12-E.

## Web Check Method

- Restarted Streamlit on `127.0.0.1:8501`.
- Checked `http://127.0.0.1:8501/_stcore/health`.
- Ran `py -3 scripts/check_phase12_context_web.py --base-url http://127.0.0.1:8501`.
- Used the in-app browser to open and interact with the real Streamlit UI.
- Submitted real AI Agent inputs and inspected visible page text for errors, context summary, and sensitive leakage.

WEB_CHECK_METHOD = `health endpoint + scripts/check_phase12_context_web.py + in-app browser real UI interaction`

## Web Check Pages

WEB_CHECK_PAGES = `首页 / 预测排名, AI Agent, AI 模拟盘, 系统监控`

## Web Check Records

| Page/Input | Actual Summary | Context Created/Visible | Secret Visible | Traceback/Error | Result |
| --- | --- | --- | --- | --- | --- |
| 首页 / 预测排名 | Page opened; ranking/home controls visible. | Not applicable | No | No | PASS |
| AI Agent: 查看我的当前持仓 | Returned current paper portfolio state with holdings. | `Context 安全摘要` visible; safe caption helper tested. | No | No | PASS |
| AI Agent: 分析当前组合风险 | Returned portfolio risk analysis and safer portfolio suggestion; retested after an initial spinner timing race. | `Context 安全摘要` visible. | No | No | PASS |
| AI Agent: 给我一个调仓建议 | Returned read-only rebalance suggestion, risk analysis, candidate evidence, and no write execution. | `Context 安全摘要` visible. | No | No | PASS |
| AI Agent: 查看系统状态 | Returned supported Agent capability/status text. | `Context 安全摘要` visible. | No | No | PASS |
| AI 模拟盘 | Account summary, current assets, risk metrics, audit sections visible. | Not applicable | No | No | PASS |
| 系统监控 | Total status, alerts, layered metrics, Runtime Reliability sections visible. | Not applicable | No | No | PASS |

Browser automation intermittently reported external Statsig network timeouts and one control-layer internal error. These were browser-plugin telemetry/control issues; page text and Streamlit health showed no application traceback or server error.

WEB_CHECK_DONE = true

WEB_CHECK_RESULT = `PASS: health ok; required pages opened; AI Agent real inputs returned; context summary visible; no confirmation_token/API key/database path/internal stack leakage observed.`

NEXT_STAGE_ALLOWED = true
