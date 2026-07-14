# Phase 6 Handoff: Runtime Reliability and Fault Injection

Disclaimer: 本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。

## Goal

Phase 6 improves runtime reliability and adds fault-injection simulations. It does not change trading strategy, paper-trading rules, RAG retrieval logic, confirmation/revalidation boundaries, live Agent behavior, or the four legacy Agent files.

## Modified Files

- `database/sqlite_store.py`: adds SQLite lock/busy retry around insert/upsert/get/list/update.
- `agent/runtime_reliability.py`: adds timeout, cancellation token, read-only retry policy, circuit breaker, latency tracker, and large-output summarizer.
- `evaluation/runtime_fault_injection.py`: adds runtime fault-injection simulations.
- `scripts/run_runtime_fault_injection.py`: CLI for fault-injection suite.
- `tests/unit/test_runtime_reliability_fault_injection.py`: Phase 6 reliability and fault-injection tests.
- Documentation indexes updated in `README.md`, `PROJECT_STRUCTURE.md`, `PROJECT_FILE_DIRECTORY.md`, `database/README.md`, `docs/AGENT_USAGE.md`, and `docs/IMPROVEMENT_BASELINE.md`.

## Database Migration

No new migration was required.

The only database change is runtime behavior: SQLite operations now retry transient `database is locked` / `database is busy` errors with short exponential backoff.

## Runtime Utilities

`agent/runtime_reliability.py` provides:

```text
run_with_timeout
run_with_retry
CancellationToken
CircuitBreaker
LatencyTracker
summarize_large_output
```

Principles:

- read-only operations can retry
- write operations are not retried by `run_with_retry` when `retry_read_only_only=True`
- cancellation raises before/after work
- circuit breaker opens after repeated failures
- large outputs are summarized/truncated before storage

## Fault Injection Cases

`evaluation/runtime_fault_injection.py` simulates:

```text
readonly_concurrency
tool_timeout
database_lock_retry
circuit_breaker
large_output
```

## Commands

Compilation:

```powershell
py -m compileall agent\runtime_reliability.py evaluation\runtime_fault_injection.py scripts\run_runtime_fault_injection.py database\sqlite_store.py
```

Focused Phase 6 tests:

```powershell
py -m pytest tests\unit\test_runtime_reliability_fault_injection.py -q
```

Fault-injection CLI:

```powershell
py scripts\run_runtime_fault_injection.py --task-count 20 --report-path runtime\phase6_fault_injection\report.json
```

Agent safety regression:

```powershell
py -m pytest tests\unit\test_runtime_reliability_fault_injection.py tests\unit\test_agent_multi_task_async.py tests\unit\test_agent_idempotency.py tests\unit\test_agent_write_requires_confirmation.py tests\unit\test_agent_paper_trade_execution.py -q
```

Database regression:

```powershell
py -m pytest tests\unit\test_database_schema.py tests\unit\test_database_repositories.py tests\unit\test_agent_runtime_persistence.py -q
```

Agent wide regression:

```powershell
$files = Get-ChildItem tests\unit -Filter test_agent*.py | ForEach-Object { $_.FullName }
py -m pytest $files -q
```

## Test Results

- Compile Phase 6 modules: passed
- Focused Phase 6 tests: `7 passed in 0.87s`
- Fault-injection CLI: `case_count=5`, `success_count=5`, `all_passed=true`
- Agent concurrency/idempotency/confirmation/execution regression: `20 passed in 16.79s`
- Database regression: `7 passed in 4.79s`
- Agent wide regression: `100 passed in 74.58s`

CLI report:

```text
runtime/phase6_fault_injection/report.json
```

Selected local metrics:

```text
readonly task_count = 20
timeout case = passed
database lock attempts = 3
circuit breaker state = open
large output original_length = 5000
large output truncated = true
```

## Page Verification

Verified in the in-app browser against:

```text
http://127.0.0.1:8503/
```

Checked:

- `AI Agent` control center renders
- scheduler quick question renders
- disclaimer renders
- no app `Traceback`, `ModuleNotFoundError`, or `NameError` was observed

Phase 6 changes are backend/evaluation reliability utilities; no UI behavior was intentionally changed.

## Known Limits

- Fault injection is local simulation, not OS-level process killing or network firewall manipulation.
- Circuit breaker utility is available but not yet wired into every external dependency call.
- Failed-run recovery and process restart recovery remain limited to existing persisted runtime snapshots and future recovery policy work.
- Resource usage metrics are represented by latency summaries; CPU/RSS collection can be added later.

## Can Phase 7 Start?

Yes. Phase 6 acceptance criteria are met for the implemented scope:

- single timeout is contained
- read-only retry is available
- write retry is avoided by policy
- SQLite lock retry is implemented
- repeated confirm/idempotency regression still passes
- P95 latency is measurable
- large output can be summarized
- Agent and database regressions pass
