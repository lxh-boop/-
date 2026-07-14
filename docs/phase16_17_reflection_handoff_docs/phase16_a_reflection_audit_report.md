# Phase 16-A Reflection Audit And Critic Protocol Design

## Stage Goal

Audit the current Agent result chain and design the Reflection Critic protocol. This stage does not connect Critic to the executor, ToolExecutor, WriteGateway, ContextManager, MemoryManager, UI logic, or database schema.

## Current State Table

| reflection_source | file | function_or_class | target_to_critic | available_refs | contains_observation | contains_replan | contains_message_trace | contains_memory_ref | contains_tool_result | contains_approval | contains_secret_risk | used_by_llm | used_by_ui | critic_check_needed | planned_critic_issue | planned_critic_action | migration_phase |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| final report | `agent/executor.py` | `run_agent_request`, `_answer`, `MessageType.FINAL_REPORT` emit | final visible answer | context refs, approval refs, message refs | yes, after Phase 15 executor observe | yes, via ReAct messages | yes | yes | summary only | yes | medium, final text can contain unsupported claims | yes | yes | yes | answer_consistency, uncertainty_disclosure, hallucination_risk | PASS / REVISE_ANSWER / BLOCK_AND_REPORT | Phase 16-C |
| portfolio proposal | `agent/executor.py`, `agent/tools/portfolio_proposal_adapters.py`, `agent/write_gateway.py` | proposal preview / pending plan | action proposal summary | approval refs, plan id, context refs | yes | yes | yes | possible | yes | yes | high, write boundary must stay protected | yes | yes | yes | approval_boundary, write_gateway_boundary, portfolio_risk_overreach | REQUIRE_APPROVAL / BLOCK_AND_REPORT | Phase 16-C |
| tool result summary | `agent/tool_engine.py` | `ToolExecutor.execute`, `UnifiedToolResult` | tool success/error/empty result | tool_call refs, artifact refs, approval refs | yes | yes | yes | possible | yes | yes for proposal tools | medium, raw tool payload must stay hidden | yes | summary UI | yes | tool_success, context_completeness, evidence_sufficiency | PASS / REPLAN_READONLY / ASK_USER | Phase 16-C |
| observation event | `agent/react/observation_types.py`, `agent/react/integration.py` | `ObservationEvent`, `record_tool_observation`, `record_executor_result_observation` | standardized observe event | observation refs, tool refs, artifact refs | yes | evaluated by policy | message emitted | memory refs supported | summarized | approval refs supported | low after sanitizer | yes via refs | yes via safe summary | yes | tool_success, stale_data, approval_boundary | PASS / REPLAN_READONLY | Phase 16-B/C |
| replan decision | `agent/react/replan_policy.py`, `agent/react/replan_types.py` | `ReplanPolicy`, `ReplanLimiter`, `ReplanDecision` | controlled replan recommendation | observation id, reason, scope | yes | yes | message emitted | no | no | approval-required supported | low after sanitizer | yes via refs | yes via safe summary | yes | replan_loop_risk, permission_blocked | PASS / BLOCK_AND_REPORT | Phase 16-C |
| message trace | `agent/communication/message_store.py`, `agent/communication/message_trace.py` | `MessageStore`, `build_message_trace` | run-level communication trace | message refs, approval refs, tool refs | yes through message types | yes | yes | no direct content | summary | yes | medium if payload not sanitized | no raw trace to LLM | safe UI summary | yes | answer_consistency, missing_tool_result | PASS / REPLAN_READONLY | Phase 16-D |
| memory safe summary | `agent/memory/memory_context_bridge.py` | `build_memory_safe_summary`, `list_memory_records_safe_page` | memory context and safe UI view | memory refs | no | no | possible source refs | yes | no | possible approval refs | medium, long-term memory must be sanitized | yes via context view | yes safe page | yes | memory_conflict, stale_data | PASS / ASK_USER | Phase 16-D |
| approval required result | `agent/tool_engine.py`, `agent/write_gateway.py`, `app/pages/ai_agent.py` | write tool guard, `execute_confirmed_plan_v2`, `_render_pending_plan` | proposal waiting for confirmation | approval refs, plan id | yes | yes | yes | no | yes | yes | high, confirmation token must never leak | no token to LLM | token input UI only | yes | approval_boundary, write_gateway_boundary | REQUIRE_APPROVAL / BLOCK_AND_REPORT | Phase 16-C |
| RAG/news/evidence result | `agent/tools/evidence_adapters.py`, `agent/tools/stock_analysis_tool.py`, `agent/services/evidence_service.py` | evidence search adapters | market evidence and cited chunks | source refs, artifact refs, chunk ids | tool observation | possible replan on empty | yes | possible evidence memory | yes | no | medium, raw evidence may be large | yes summary | yes summary | yes | evidence_sufficiency, stale_data, hallucination_risk | PASS / REPLAN_READONLY / REVISE_ANSWER | Phase 16-C |
| risk analysis result | `agent/tools/portfolio_risk_adapters.py`, `agent/tools/portfolio_risk_tool.py`, `app/pages/ai_paper_trading.py` | portfolio risk services | risk report / suitability | artifact refs, source refs | tool observation | possible | yes | possible | yes | no direct approval | medium, overreach risk | yes summary | yes | yes | risk_profile_alignment, portfolio_risk_overreach | PASS / REVISE_ANSWER / REQUIRE_APPROVAL | Phase 16-C |
| system status result | `agent/tools/system_auxiliary_adapters.py`, `agent/tools/scheduler_tool.py`, `app/pages/system_monitor.py` | scheduler/system status tools | scheduler/status report | message refs, runtime metrics | tool observation | possible | yes | no | yes | no | low | yes summary | yes | yes | stale_data, tool_success | PASS / REPLAN_READONLY | Phase 16-C |
| AI Agent rendered answer | `app/pages/ai_agent.py` | `_normalise_answer`, `_render_result_details`, `_render_history` | user-visible answer and safe details | context/message/react/memory safe refs | yes safe summary | yes safe summary | yes safe summary | yes safe summary | lazy sanitized | pending plans | medium, UI must not expose raw internals | no | yes | yes | uncertainty_disclosure, raw_payload_ui_exposure | PASS / REVISE_ANSWER | Phase 16-D |

## CriticResult Protocol Design

Target model: `CriticResult`.

Planned fields:

- `critic_id`
- `conversation_id`
- `run_id`
- `task_id`
- `target_type`
- `target_ref`
- `target_summary`
- `verdict`
- `action`
- `severity`
- `score`
- `issues`
- `evidence_refs`
- `observation_refs`
- `replan_refs`
- `message_refs`
- `memory_refs`
- `approval_refs`
- `revision_instruction`
- `replan_hint`
- `handoff_hint`
- `requires_user_confirmation`
- `created_at`
- `metadata`

Planned actions:

- `PASS`
- `REVISE_ANSWER`
- `REPLAN_READONLY`
- `ASK_USER`
- `REQUIRE_APPROVAL`
- `BLOCK_AND_REPORT`
- `HANDOFF_REQUESTED`

Planned issue categories:

- `evidence_sufficiency`
- `tool_success`
- `context_completeness`
- `risk_profile_alignment`
- `write_gateway_boundary`
- `approval_boundary`
- `answer_consistency`
- `uncertainty_disclosure`
- `stale_data`
- `hallucination_risk`
- `memory_conflict`
- `portfolio_risk_overreach`

Planned target types:

- `FINAL_ANSWER`
- `TOOL_RESULT`
- `PORTFOLIO_PROPOSAL`
- `OBSERVATION`
- `REPLAN_DECISION`
- `MESSAGE_TRACE`
- `MEMORY_SUMMARY`
- `APPROVAL_REQUEST`
- `EVIDENCE_RESULT`
- `RISK_RESULT`
- `SYSTEM_STATUS`

## Planned Policy

`CriticPolicy` should be deterministic first:

- Reject or block any target that implies direct writes outside WriteGateway.
- Require approval when a result contains proposal-like or write-like effects.
- Request read-only replan when tool result is empty, failed, or evidence is insufficient.
- Ask user when required user goal, stock code, date, or confirmation context is missing.
- Revise answer only when business result is usable but user-visible wording is unsupported, too certain, or missing uncertainty/disclaimer.
- Handoff only as a structured recommendation for Phase 17; no direct specialist execution in Phase 16.

## Sensitive Field Risk Identification

Known sensitive fields:

- `confirmation_token`
- API keys and tokens
- database/local paths
- internal stack traces
- `raw_positions`
- `raw_evidence`
- `raw_tool_payload`

Existing mitigations:

- `ContextSanitizer`, `MessageSanitizer`, `ObserveSanitizer`, and `MemorySanitizer`.
- AI Agent UI only renders safe summaries and lazy sanitized detail blocks.
- Write confirmation input is accepted only by UI/WriteGateway and not sent to Critic design targets.

## Planned Integration Points

- Phase 16-B: add reflection core model, policy, sanitizer, and safe window.
- Phase 16-C: call CriticEngine near the final read-only result path in `agent/executor.py`, after Phase 15 observation/replan generation and before final UI return.
- Phase 16-C: emit `REFLECTION_*` messages through existing MessageBus only.
- Phase 16-D: show reflection safe summary in AI Agent UI and System Monitor.

## Files Added Or Modified

- Added `docs/phase16_a_reflection_audit_report.md`.
- No runtime code changed in this stage.

## Tests

```powershell
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
```

Result: PASS.

```powershell
py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py tests/unit/test_phase11_p0_write_gateway.py tests/unit/test_agent_write_requires_confirmation.py tests/unit/test_agent_action_proposal_gateway.py tests/unit/test_phase12_context_core.py tests/unit/test_phase12_context_policy.py tests/unit/test_phase12_context_executor_integration.py tests/unit/test_phase13_message_core.py tests/unit/test_phase13_message_store_bus.py tests/unit/test_phase13_message_policy.py tests/unit/test_phase14_memory_manager.py tests/unit/test_phase14_memory_tool_ui.py tests/unit/test_phase15_observation_core.py tests/unit/test_phase15_replan_policy.py tests/unit/test_phase15_agent_chat_loading.py -q
```

Result: PASS, `56 passed`, `9 warnings`.

```powershell
py -3 scripts\check_phase15_react_loading_web.py
py -3 scripts\check_phase13_communication_web.py
```

Result: PASS.

## Web Check

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = health endpoint + Streamlit AppTest scripts + in-app browser real page switching/read-only visible text check.

WEB_CHECK_PAGES =

- `http://127.0.0.1:8501/_stcore/health`
- Home / prediction ranking
- AI Agent
- AI paper trading
- System monitor

WEB_CHECK_RESULT = PASS. Health returned `ok`; AppTest scripts reported 0 page errors; browser switching confirmed page markers and no visible `Traceback`, `ModuleNotFoundError`, `NameError`, `confirmation_token`, `agent_quant.db`, or `raw_tool_payload`.

WEB_CHECK_ERRORS = Browser emitted an unrelated host Statsig network timeout log during local page inspection; local app checks were unaffected.

## Unfinished Items

- No Critic runtime model is implemented yet.
- No Executor integration is implemented yet.
- No UI Reflection summary is implemented yet.

NEXT_STAGE_ALLOWED = true
