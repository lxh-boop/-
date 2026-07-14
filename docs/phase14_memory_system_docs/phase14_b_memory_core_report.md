# Phase 14-B Memory Core Report

## Stage Goal

Build the Phase 14 memory core model and safety layer without connecting it to the main executor chain.

Implemented:

- `MemoryRecord`
- `MemoryType`
- `MemoryScope`
- `MemoryVisibility`
- `MemoryStatus`
- `MemoryPolicy`
- `MemorySanitizer`
- `MemoryImportanceScorer`

## Added / Modified Files

- `agent/memory/legacy.py`
  - Moved from the previous `agent/memory.py`.
  - Legacy public APIs remain re-exported from `agent.memory`.
- `agent/memory/__init__.py`
  - Compatibility package entrypoint.
  - Re-exports old `LayeredMemoryService`, `MemoryWeights`, `score_memory`, etc.
  - Exports new Phase 14 model / policy / sanitizer classes.
- `agent/memory/memory_types.py`
  - Core memory enums and `MemoryRecord`.
- `agent/memory/memory_policy.py`
  - Field visibility classification and storage validation.
- `agent/memory/memory_sanitizer.py`
  - Storage / LLM / UI / audit sanitization.
- `agent/memory/memory_importance.py`
  - Deterministic importance scoring.
- `tests/unit/test_phase14_memory_core.py`
- `tests/unit/test_phase14_memory_policy.py`
- `docs/phase14_b_memory_core_report.md`

## Core Implementation Notes

- Existing import path remains compatible:
  - `from agent.memory import LayeredMemoryService`
  - `from agent.memory import MemoryWeights`
  - `from agent.memory import score_memory`
- The new package does not replace `ContextManager`, `MessageBus`, `ArtifactStore`, `EvidenceService`, or `WriteGateway`.
- No executor, tool executor, context, communication, UI, portfolio, strategy, or write path was changed in this stage.
- `MemoryRecord.to_legacy_memory_item()` preserves compatibility with the existing `memory_items` storage shape.
- `MemoryRecord.from_legacy_memory_item()` maps existing DB rows such as `preference`, `risk_preference`, and `conversation_summary` into Phase 14 memory categories while preserving the legacy subtype.

## Security Filtering Result

Covered forbidden data:

- `confirmation_token`
- `confirmation_token_hash`
- `api_key`
- `tushare_token`
- `password`
- `secret`
- local database path / `agent_quant.db`
- local absolute paths
- `Traceback` / internal stack text
- `raw_positions`
- `raw_evidence`
- `raw_tool_payload`

Policy result:

- Secret fields are not storable.
- System-only and audit-only fields are not visible to LLM/UI memory views.
- Raw large objects are summarized as refs/counts instead of stored directly.
- Long-term user facts such as user preference/profile memories require confirmation or an explicit confirmed user source.
- One-time operation instructions are rejected as long-term user facts.
- Approval memory is limited to safe summary fields such as `plan_id`, `status`, `token_present`, and `summary`.

## Test Commands And Results

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts`
  - PASS
- `py -3 -m pytest tests/unit/test_phase14_memory_core.py -q`
  - PASS, 4 passed
- `py -3 -m pytest tests/unit/test_phase14_memory_policy.py -q`
  - PASS, 4 passed
- `py -3 -m pytest tests/unit/test_phase12_context_policy.py -q`
  - PASS, 4 passed
- `py -3 -m pytest tests/unit/test_phase13_message_policy.py -q`
  - PASS, 3 passed
- `py -3 -m pytest tests/unit/test_agent_layered_memory.py tests/unit/test_multi_agent_phase4_memory.py -q`
  - PASS, 16 passed

## Real Web Check Result

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = health + Streamlit AppTest + Playwright Chromium real render + in-app browser root render

WEB_CHECK_PAGES = [
  "http://127.0.0.1:8501/_stcore/health",
  "首页 / 预测排名",
  "AI Agent",
  "AI 模拟盘",
  "系统监控"
]

WEB_CHECK_RESULT = PASS

WEB_CHECK_ERRORS = []

Details:

- Health endpoint returned `ok`.
- `scripts/check_phase13_communication_web.py` reported 0 page exceptions and 0 page errors for all four pages.
- Playwright Chromium opened `http://127.0.0.1:8501`, clicked the top-level page radio selector, and verified visible markers for:
  - home / prediction ranking
  - AI paper trading
  - AI Agent
  - system monitor
- Browser-visible text checks found none of:
  - `Traceback`
  - `ModuleNotFoundError`
  - `NameError`
  - `KeyError`
  - `confirmation_token`
  - `api_key`
  - `tushare_token`
  - `agent_quant.db`
- AI Agent AppTest used a temp DB and temp output directory, entered:
  - `查看我的当前持仓`
  - `分析当前组合风险`
  - `给我一个调仓建议`
  - `查看系统状态`
- Each Agent input rendered without Streamlit exceptions/errors and without sensitive field leakage.

Non-blocking note:

- The existing system monitor page can emit Streamlit/PyArrow dataframe auto-fix warnings in script stderr. The page check itself reported no UI exception, no UI error, and no visible internal stack. This issue predates Phase 14-B and was not changed in this stage.

## Failed Items

None.

## Unfinished Items

- No `MemoryStore`, `MemoryRetriever`, `WorkingMemory`, `MemoryManager`, `Consolidator`, or `Pruner` is implemented in this stage.
- No executor/tool/context/message/UI integration is implemented in this stage.

NEXT_STAGE_ALLOWED = true
