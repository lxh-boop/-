# Agent Capability Benchmark Pipeline Repair Baseline

- Captured: 2026-07-20
- Git commit: `4a7afff`; working tree contained pre-existing user changes and was not reset.
- Provider: `openai_compatible`; model: `deepseek-v4-flash`.
- Local configuration: API key present = `true`; base URL present = `true`. No secret value, URL, prompt or response is recorded here.
- Repaired configuration hash: `3a514c058686d6bf`.
- Trace schema: `l1_llm_receipt_v2`; scorer: `l1_validity_partition_v2`.

## Entry points and evidence locations

- Formal Agent entry: `agent.executor.run_agent_request`.
- LLM receipt writer: `agent.llm_audit` through `LLMClient.chat_audited`.
- Planner/reviewer implementation: `agent.intent_decomposition.llm_decomposer`.
- Isolated runner: `benchmarks/agent_capability/run_benchmark.py`.
- Raw evidence: `outputs/benchmarks/agent_capability/raw_runs.jsonl`.
- Normalized evidence: `outputs/benchmarks/agent_capability/normalized_traces.jsonl`.
- Preserved failure evidence: `outputs/benchmarks/agent_capability/failures.jsonl`.

## Pre-repair observed state

The preserved historical run set contained 900 attempted rows: 540 development, 180 validation and 180 hidden. The historical model configuration hash was `380d6c463aa543f2`. At least 375 rows contain the provider error identifier `llm_insufficient_balance`.

Those are provider failures, not evidence of poor Agent capability. The prior aggregate incorrectly emitted a numeric `forbidden_capability_rate=1` with zero valid hidden samples. The repaired pipeline makes every Agent metric N/A when no valid auditable sample exists, separately reports infrastructure/provider rates, and retains the earlier raw/failure artifacts.

## Initial classification policy

| Condition | Classification | Included in Agent metrics |
|---|---|---|
| Provider request recorded but unsuccessful | provider failure | No |
| Missing formal entry, planner receipt, persisted trace, or required reviewer receipt | infrastructure failure | No |
| Formal entry, successful real LLM planner, required reviewer and readable persisted trace all present | normal scoring candidate | Yes |
| Normal scoring candidate fails the task scorer | Agent capability failure | Yes |

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
