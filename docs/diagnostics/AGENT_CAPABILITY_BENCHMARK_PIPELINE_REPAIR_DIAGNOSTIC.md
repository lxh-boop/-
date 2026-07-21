# Agent Capability Benchmark Pipeline Repair Diagnostic

- Date: 2026-07-20
- Configuration hash: `3a514c058686d6bf`
- Provider/model: `openai_compatible` / `deepseek-v4-flash`
- Scope: isolated hidden-set minimum verification only; no six-category or full run was started.

## Minimum verification result

| Requirement | Result |
|---|---:|
| Attempted samples | 2 |
| Real provider request recorded | 2 / 2 |
| Formal `run_agent_request` entry recorded | 2 / 2 |
| Planner receipt persisted and visible to runner | 2 / 2 |
| Valid Agent-scoring samples | 0 / 2 |
| Provider failures | 2 / 2 |
| Infrastructure failures | 0 / 2 |
| Agent metrics | N/A |

The expansion gate requires at least one valid sample. It did not pass because both recorded provider attempts returned HTTP 402 / `Insufficient Balance`; the required next action is to restore provider availability and rerun these same two isolated samples, not to broaden the benchmark.

## Stage matrix

| Stage | L1-A-025 | L1-A-026 | Runner visibility | Diagnosis |
|---|---|---|---|---|
| Formal entry | actual | actual | persisted in runtime/result | `agent.executor.run_agent_request` used |
| Planner | actual request, failed | actual request, failed | persisted `LLM_CALL` | provider call failure |
| Goal reviewer | not called | not called | correctly absent | not required after planner provider failure |
| Plan reviewer | not called | not called | correctly absent | not required after planner provider failure |
| Completion/report path | actual request, failed | actual request, failed | persisted `LLM_CALL` | provider call failure |
| Critic | no confirmed call | no confirmed call | absent | downstream route did not produce an auditable receipt |
| Trace persistence | successful | successful | JSONL read by runner | not a trace persistence defect |
| Validity | invalid | invalid | explicit classification | provider failure; excluded from Agent score |

## Failure distinction

- **Provider did not call:** not observed. Both samples contain an actual persisted planner request receipt.
- **Provider call failed:** observed for both samples. The response was unsuccessful; no planner response/schema receipt was available.
- **Provider call succeeded but audit event missing:** not observed.
- **Audit event missing from persistent trace:** not observed.
- **Runner mapping problem:** not observed; the runner loaded the persisted receipt.
- **Validity-rule problem:** not observed; validity correctly excludes a failed provider request and does not impose a reviewer requirement after that terminal failure.

## Scoring status

All Agent and safety metrics are N/A, including `forbidden_capability_rate`; no zero denominator is converted to a failure value. Raw runs, normalized traces and failures remain preserved in `outputs/benchmarks/agent_capability/`.

本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。
