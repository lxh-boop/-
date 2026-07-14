# Phase 14-C Memory Store / Retriever Report

## Stage Goal

Build the memory storage and retrieval foundation without connecting it to the main Agent execution chain.

Implemented:

- `WorkingMemory`
- `SQLiteMemoryStore`
- `MemoryRetriever`
- `GraphMemoryStore` placeholder
- `VectorMemoryStore` placeholder

## Added / Modified Files

- `agent/memory/working_memory.py`
  - In-memory working memory with TTL, user isolation, delete, and search.
- `agent/memory/memory_store.py`
  - Independent SQLite memory store.
  - Default path: `outputs/memory/memory_store.sqlite`.
  - Does not modify the business database schema.
- `agent/memory/memory_retriever.py`
  - Deterministic retrieval by type, topic, entity, time, and importance.
- `agent/memory/graph_memory_store.py`
  - Interface placeholder; no Neo4j dependency.
- `agent/memory/vector_memory_store.py`
  - Interface placeholder; no Qdrant dependency.
- `agent/memory/__init__.py`
  - Exports Stage C classes while preserving legacy exports.
- `tests/unit/test_phase14_working_memory.py`
- `tests/unit/test_phase14_memory_store_retriever.py`
- `docs/phase14_c_memory_store_retriever_report.md`

## Core Implementation Notes

- `WorkingMemory`:
  - Stores only sanitized `MemoryRecord` instances.
  - Forces records into `MemoryType.WORKING`.
  - Applies TTL and removes expired records.
  - Enforces user isolation on get/search/delete.
- `SQLiteMemoryStore`:
  - Uses a separate SQLite file, not `data/agent_quant.db`.
  - Creates its own `memory_records` table and indexes.
  - Sanitizes records before persistence.
  - Applies `MemoryPolicy.assert_can_store()` before writing.
  - Supports roundtrip, user filter, memory type filter, topic filter, stock code filter, importance filter, soft delete, and count.
- `MemoryRetriever`:
  - Merges optional working memory and SQLite store records.
  - Scores deterministically using semantic token overlap, entity match, topic match, importance, and confidence.
  - Excludes expired records.
- `GraphMemoryStore` and `VectorMemoryStore`:
  - Deliberately return `available() == False`.
  - Raise `NotImplementedError` for query/write methods.
  - No external service or dependency is introduced.

## Security Filtering Result

Verified:

- `confirmation_token` does not persist.
- `api_key` does not persist.
- `tushare_token` does not persist.
- local database path / `agent_quant.db` does not persist.
- traceback/internal stack text does not enter LLM/UI memory views.
- `raw_positions` and `raw_evidence` are summarized instead of stored directly.
- Unconfirmed long-term user preference/profile memory is rejected.
- Memory infrastructure has no method that writes paper trading, portfolio, or strategy state.

## Test Commands And Results

- `py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts`
  - PASS
- `py -3 -m pytest tests/unit/test_phase14_working_memory.py -q`
  - PASS, 3 passed
- `py -3 -m pytest tests/unit/test_phase14_memory_store_retriever.py -q`
  - PASS, 5 passed
- `py -3 -m pytest tests/unit/test_phase14_memory_core.py -q`
  - PASS, 4 passed
- `py -3 -m pytest tests/unit/test_phase14_memory_policy.py -q`
  - PASS, 4 passed
- `py -3 -m pytest tests/unit/test_agent_layered_memory.py tests/unit/test_multi_agent_phase4_memory.py -q`
  - PASS, 16 passed

## Real Web Check Result

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = health + Streamlit AppTest + Playwright Chromium real render

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
- `scripts/check_phase13_communication_web.py` reported 0 page exceptions and 0 page errors.
- Playwright Chromium opened the app, clicked the top-level `页面` radio selector, and verified visible page markers for home, AI paper trading, AI Agent, and system monitor.
- Browser-visible text checks found none of:
  - `Traceback`
  - `ModuleNotFoundError`
  - `NameError`
  - `KeyError`
  - `confirmation_token`
  - `api_key`
  - `tushare_token`
  - `agent_quant.db`
- AI Agent AppTest used a temp DB/output directory and entered:
  - `查看我的当前持仓`
  - `分析当前组合风险`
  - `给我一个调仓建议`
  - `查看系统状态`
- Each Agent input rendered without Streamlit exceptions/errors and without sensitive field leakage.

Non-blocking note:

- The existing system monitor page can emit Streamlit/PyArrow dataframe auto-fix warnings in script stderr. No UI exception/error or visible internal stack was detected. This predates Phase 14-C and was not changed in this stage.

## Failed Items

None.

## Unfinished Items

- `MemoryManager`, `MemoryConsolidator`, and `MemoryPruner` are not implemented in this stage.
- No Context/Message/Tool/UI integration is implemented in this stage.
- Graph and vector memory stores are placeholders only.

NEXT_STAGE_ALLOWED = true
