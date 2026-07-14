# Phase 16-B Reflection Critic Core Report

## Scope

Implemented the Reflection Critic core layer only. This stage does not connect Critic to `agent/executor.py`, `agent/tool_engine.py`, `WriteGateway`, ContextManager, MessageBus, MemoryManager, Handoff, or UI runtime behavior.

## Added Files

- `agent/reflection/__init__.py`
- `agent/reflection/critic_types.py`
- `agent/reflection/critic_policy.py`
- `agent/reflection/critic_sanitizer.py`
- `agent/reflection/critic_window.py`
- `tests/unit/test_phase16_critic_core.py`
- `tests/unit/test_phase16_critic_policy.py`

## CriticResult Model

`CriticResult` now supports:

- `critic_id`, `conversation_id`, `run_id`, `task_id`
- `target_type`, `target_ref`, `target_summary`
- `verdict`, `action`, `severity`, `score`
- `issues`
- `evidence_refs`, `observation_refs`, `replan_refs`, `message_refs`, `memory_refs`, `approval_refs`
- `revision_instruction`, `replan_hint`, `handoff_hint`
- `requires_user_confirmation`
- `created_at`, `metadata`

`CriticIssue` stores only issue summaries, structured categories, severity, and references. Raw payload, raw positions, raw evidence, confirmation tokens, and private reasoning are not part of the safe LLM/UI projection.

## CriticAction List

- `PASS`
- `REVISE_ANSWER`
- `REPLAN_READONLY`
- `ASK_USER`
- `REQUIRE_APPROVAL`
- `BLOCK_AND_REPORT`
- `HANDOFF_REQUESTED`

## CriticPolicy Rules

Implemented:

- `classify_issue()`
- `score_result()`
- `decide_action()`
- `can_show_to_llm()`
- `can_show_to_ui()`
- `requires_redaction()`

Key behavior:

- Sensitive data exposure -> `BLOCK_AND_REPORT`
- Permission blocked -> `BLOCK_AND_REPORT`
- Write without approval -> `REQUIRE_APPROVAL` or blocking report when severity is blocking
- Missing user information -> `ASK_USER`
- Evidence gap / empty result / tool failure -> `REPLAN_READONLY`
- Risk policy or user preference mismatch -> `REVISE_ANSWER` or `REQUIRE_APPROVAL`
- Handoff need is represented only as `HANDOFF_REQUESTED`; no Handoff runtime is implemented in Phase 16-B.

## CriticSanitizer Result

Implemented:

- `sanitize_for_llm()`
- `sanitize_for_ui()`
- `sanitize_for_audit()`
- `sanitize_for_context()`

Sanitizer filters or summarizes:

- `confirmation_token`
- API keys, Tushare token, authorization, cookie, password, secret
- database paths and local paths
- internal stacks and tracebacks
- `raw_positions`
- `raw_evidence`
- `raw_tool_payload`
- `full_payload`
- private chain-of-thought fields

Large raw objects are projected as summaries such as `positions_summary`, `evidence_summary`, and `tool_payload_summary` with safe refs only.

## CriticWindow Rules

Implemented:

- `trim_critic_results_to_budget()`
- `summarize_old_critic_results()`
- `keep_blocking_issues()`
- `estimate_critic_size()`

Blocking or approval-related Critic results are retained even under tight budgets. Older non-blocking results can be summarized.

## Tests

```powershell
py -3 -m compileall -q agent app portfolio scoring rag pipelines database scripts
```

Result: PASS.

```powershell
py -3 -m pytest tests/unit/test_phase11_intent_tool_engine.py tests/unit/test_phase11_p0_write_gateway.py -q
```

Result: PASS, `13 passed`, `7 warnings`.

```powershell
py -3 -m pytest tests/unit/test_agent_write_requires_confirmation.py tests/unit/test_agent_action_proposal_gateway.py -q
```

Result: PASS, `4 passed`.

```powershell
py -3 -m pytest tests/unit/test_phase12_context_core.py tests/unit/test_phase12_context_policy.py tests/unit/test_phase12_context_executor_integration.py -q
```

Result: PASS, `8 passed`, `2 warnings`.

```powershell
py -3 -m pytest tests/unit/test_phase13_message_core.py tests/unit/test_phase13_message_store_bus.py tests/unit/test_phase13_message_policy.py -q
```

Result: PASS, `9 passed`.

```powershell
py -3 -m pytest tests/unit/test_phase14_memory_manager.py tests/unit/test_phase14_memory_tool_ui.py -q
```

Result: PASS, `8 passed`.

```powershell
py -3 -m pytest tests/unit/test_phase15_observation_core.py tests/unit/test_phase15_replan_policy.py tests/unit/test_phase15_agent_chat_loading.py -q
```

Result: PASS, `14 passed`.

```powershell
py -3 -m pytest tests/unit/test_phase16_critic_core.py tests/unit/test_phase16_critic_policy.py -q
```

Result: PASS, `8 passed`.

Known warnings are existing `datetime.utcnow()` deprecation warnings in `agent/capability_index.py`.

## Web Check

WEB_CHECK_DONE = true

WEB_CHECK_METHOD = health endpoint + existing Streamlit AppTest scripts + in-app browser screenshot and real top-level radio page switching.

WEB_CHECK_PAGES =

- `http://127.0.0.1:8501/_stcore/health`
- Home / prediction ranking
- AI Agent
- AI paper trading
- System monitor

WEB_CHECK_RESULT = PASS. Health returned `ok`; `scripts/check_phase15_react_loading_web.py` and `scripts/check_phase13_communication_web.py` passed; browser screenshot confirmed the app rendered; browser clicked Home, AI Agent, AI paper trading, and System monitor top-level radio items with exactly one locator match each. Each page contained its expected marker and no visible `Traceback`, `ModuleNotFoundError`, `NameError`, `confirmation_token`, `agent_quant.db`, `raw_tool_payload`, or `raw_positions`.

WEB_CHECK_ERRORS = []

## Next Stage Gate

NEXT_STAGE_ALLOWED = true
