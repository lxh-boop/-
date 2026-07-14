# Phase 4 Handoff: Layered Agent Memory

Disclaimer: 本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## Goal

Phase 4 adds controlled layered memory for the unified Agent runtime. It reuses existing runtime tables and does not create a second memory, Agent, RAG, database, or paper-trading system.

The four legacy Agent files were not modified:

```text
agent/portfolio_qa_agent.py
agent/event_impact_agent.py
agent/portfolio_review_agent.py
agent/model_monitor_agent.py
```

## Modified Files

- `agent/memory.py`: implements `LayeredMemoryService`, memory scoring, semantic write policy, delete, supersede, and layered retrieval.
- `agent/context/gatherer.py`: ContextBuilder now obtains memory through `LayeredMemoryService.retrieve_layered_memory(...)`.
- `database/repositories/agent_repository.py`: adds repository helpers for conversation summaries, memory lookup, memory update, and memory links.
- `tests/unit/test_agent_layered_memory.py`: Phase 4 memory safety and retrieval tests.
- Documentation indexes updated in `README.md`, `PROJECT_STRUCTURE.md`, `PROJECT_FILE_DIRECTORY.md`, `database/README.md`, `docs/AGENT_USAGE.md`, and `docs/IMPROVEMENT_BASELINE.md`.

## Database Migration

No new migration was required.

Phase 4 reuses:

```text
conversations
messages
conversation_summaries
memory_items
memory_links
action_proposals
agent_runs
```

## Memory Layers

Working Memory:

- current conversation messages
- current run metadata
- pending action proposals

Episodic Memory:

- conversation summaries
- historical Agent run summaries

Semantic Memory:

- long-term preference
- risk preference
- investment goal
- language preference
- stable constraint

## Scoring

The retrieval score is:

```text
S(m,q) =
0.35 * semantic
+ 0.25 * recency
+ 0.20 * importance
+ 0.20 * entity
```

The weights are validated to sum to 1.0.

Entity scoring preserves stock-code relevance. Expired and deleted memories are excluded before scoring.

## Safety Rules

Implemented:

- user isolation for all layers
- source type and source id required for semantic memory writes
- `memory_links` source traceability
- `valid_until` expiry exclusion
- soft delete via `status=deleted`
- user correction via `supersedes_memory_id` and `status=superseded`
- one-time operations are rejected as semantic memory
- `agent_inference` is rejected as a user fact

Accepted semantic source types:

```text
user_message
user_feedback
profile_setting
manual_import
confirmed_user_preference
```

Accepted semantic memory types:

```text
long_term_preference
risk_preference
investment_goal
language_preference
stable_constraint
```

## Commands

Compilation:

```powershell
py -m compileall agent\memory.py database\repositories\agent_repository.py
py -m compileall agent\memory.py agent\context\gatherer.py agent\context
```

Focused Phase 4 tests:

```powershell
py -m pytest tests\unit\test_agent_layered_memory.py -q
```

Memory + ContextBuilder + Agent safety regression:

```powershell
py -m pytest tests\unit\test_agent_layered_memory.py tests\unit\test_agent_context_builder.py tests\unit\test_agent_runtime_unified.py tests\unit\test_agent_runtime_persistence.py tests\unit\test_agent_write_requires_confirmation.py -q
```

Agent wide regression:

```powershell
$files = Get-ChildItem tests\unit -Filter test_agent*.py | ForEach-Object { $_.FullName }
py -m pytest $files -q
```

## Test Results

- Compile memory/repository: passed
- Compile memory/context: passed
- Phase 4 focused tests: `8 passed in 3.24s`
- Memory + ContextBuilder + Agent safety regression: `18 passed in 27.47s`
- Agent wide regression: `96 passed in 58.08s`

Covered:

- different users do not share memory
- old preference is superseded by user correction
- deleted memory is not recalled
- expired memory does not enter context
- one-time operation is not promoted to long-term memory
- Agent inference is not stored as user fact
- memory source links are traceable
- working and episodic memory are user-scoped

## Page Verification

Verified in the in-app browser against:

```text
http://127.0.0.1:8503/
```

Checked:

- home page renders without application errors
- `AI Agent` page renders control center, metrics, quick questions, pending plan panel, tools panel, and disclaimer
- clicked `查看当前模拟盘账户和持仓`
- Agent completed a read-only paper-portfolio query with `agent_run_05705fe532dc / completed`
- answer included current paper holdings and the required disclaimer
- no app `Traceback`, `ModuleNotFoundError`, or `NameError` was observed

The browser automation client logged one external telemetry timeout; it did not affect the local app check.

## Metrics

Local Phase 4 test metrics:

```text
semantic weight = 0.35
recency weight = 0.25
importance weight = 0.20
entity weight = 0.20
total = 1.00
focused memory tests = 8 passed
agent wide regression = 96 passed
```

## Known Limits

- Phase 4 does not add an in-app memory management page yet.
- Long conversation summarization is not automatically generated; the service reads existing `conversation_summaries`.
- Semantic memory writes are explicit API calls only. Agent responses are not automatically promoted into long-term memory.
- Deletion is implemented as soft delete through `status=deleted`; physical purge can be added later if required.

## Can Phase 5 Start?

Yes. Phase 4 acceptance criteria are met:

- three memory layers are available
- history no longer enters context as an unbounded raw list
- deleted and expired memory is excluded
- user correction can supersede old memory
- one-time operations and Agent inference are not stored as stable user facts
- existing Agent runtime, confirmation safety, paper-trading rules, RAG, and legacy Agent files remain unchanged
