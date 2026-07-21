# Agent Capability Benchmark Pipeline Repair Report

## Outcome

The measurement pipeline repair is implemented and verified with two real, isolated hidden-set attempts (`L1-A-025`, `L1-A-026`). Both requests entered through `agent.executor.run_agent_request`, produced persisted, redacted Planner `LLM_CALL` receipts, and were visible to the runner. Both provider calls failed with HTTP 402 / `Insufficient Balance` before a usable Planner response was returned.

Consequently, this is a pipeline/provider diagnostic outcome, not an Agent capability result:

| Field | Value |
|---|---:|
| Attempted | 2 |
| Real LLM request receipt rate | 1.0 |
| Formal entry rate | 1.0 |
| Planner receipt rate | 1.0 |
| Valid Agent-scoring samples | 0 |
| Provider failure rate | 1.0 |
| Infrastructure failure rate | 0.0 |
| Agent/safety metrics | N/A |

## Repairs delivered

- Formal-entry provenance is persisted by `run_agent_request`; the runner cannot forge it.
- Real LLM calls are stored as redacted, durable `LLM_CALL` events with stage, timing, provider/model, response/schema status, request ID when exposed, error type, and explicit `fallback_used=false` / `mock_used=false`.
- Validity is lower-bounded by formal entry, real Planner call and persisted trace. Reviewer evidence is required only when a successful Planner response reaches the normal review path; a terminal/provider failure before review is not misclassified as a missing reviewer.
- Provider and infrastructure failures are excluded from Agent metrics. Invalid rows remain in raw runs, normalized traces and failures.
- Empty Agent samples now yield N/A for every capability and safety metric, including `forbidden_capability_rate`, with explicit numerator, denominator, status and reason.
- Resume treats invalid provider/infrastructure rows as retryable rather than complete.

## Publication decision

No official hidden-set capability report was updated because `valid sample_count = 0`. The required six-category and full gradual runs were not started. See `AGENT_CAPABILITY_BENCHMARK_PIPELINE_REPAIR_DIAGNOSTIC.md` and `AGENT_CAPABILITY_BENCHMARK_INFRASTRUCTURE_DIAGNOSTIC.md` for the preserved failure evidence and stage matrix.

## Next gated action

Restore the configured provider's available balance/access, then rerun only `L1-A-025` and `L1-A-026` once. Expand only after at least one valid sample and the stated minimum evidence gates pass.

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
