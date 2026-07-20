from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.console_trace import trace_event
from core.llm.runtime_settings import LLMRuntimeSettings

from agent.intent_decomposition import decompose_intent
from agent.goal_planning import attach_goal_planning_to_decomposition
from agent.intent_decomposition.schemas import PROTECTED_OPERATION_TYPES, WRITE_INTENTS
from agent.parameter_extractor import extract_parameters


@dataclass(frozen=True)
class RoutedIntent:
    intent: str
    parameters: dict[str, Any]
    query: str
    decomposition: dict[str, Any] = field(
        default_factory=dict
    )
    execution_route: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "parameters": dict(self.parameters),
            "query": self.query,
            "decomposition": dict(self.decomposition),
            "execution_route": self.execution_route,
        }


def _merge_parameters(
    extracted: dict[str, Any],
    planned: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(extracted)

    for key, value in planned.items():
        if value not in ("", None):
            merged[key] = value

    return merged


def _executor_route_for_decomposition(decomposition) -> str:
    if decomposition.need_clarification:
        return "clarification"
    if not decomposition.tasks:
        return "unsupported"
    intents = {task.intent for task in decomposition.tasks}
    if intents in ({"confirm_execute"}, {"reject_execute"}):
        return "approval_resume"
    if intents & WRITE_INTENTS or any(task.operation_type in PROTECTED_OPERATION_TYPES for task in decomposition.tasks):
        return "proposal_flow"
    if len(decomposition.tasks) == 1 and not decomposition.tasks[0].depends_on:
        return "single_read_task"
    return "read_only_dag"


def _decomposition_payload(decomposition, execution_route: str) -> dict[str, Any]:
    payload = decomposition.to_dict()
    diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
    diagnostics["executor_route"] = execution_route
    diagnostics.setdefault("execution_task_source", "task_plan")
    payload["diagnostics"] = diagnostics
    return payload


def route_agent_query(
    query: str,
    *,
    llm_api_key: str | None = None,
    llm_base_url: str | None = None,
    llm_model: str | None = None,
    llm_settings: LLMRuntimeSettings | None = None,
    reply_language: str = "zh",
    context: dict[str, Any] | None = None,
    enable_llm: bool = True,
) -> RoutedIntent:
    decomposition = decompose_intent(
        query,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        llm_settings=llm_settings,
        reply_language=reply_language,
        context=context,
        enable_llm=enable_llm,
    )
    decomposition = attach_goal_planning_to_decomposition(
        decomposition,
        context=context,
    )
    execution_route = _executor_route_for_decomposition(decomposition)
    decomposition_dict = _decomposition_payload(decomposition, execution_route)
    trace_event(
        "router.plan_ready",
        {"execution_route": execution_route, "decomposition": decomposition_dict},
        run_id=str((context or {}).get("run_id") or ""),
    )

    # ParameterExtractor is permitted only for hard-control commands.  For
    # business requests, the LLM TaskPlan is the sole parameter source; rule or
    # regex extraction remains visible to the LLM as advisory RuleHints.
    extracted = extract_parameters(query) if decomposition.route_layer == "hard_rule" else {}

    if (
        decomposition.diagnostics.get("error_code")
        == "insufficient_balance"
    ):
        return RoutedIntent(
            intent="llm_insufficient_balance",
            parameters=extracted,
            query=str(query or ""),
            decomposition=decomposition_dict,
            execution_route=execution_route,
        )

    if decomposition.need_clarification:
        return RoutedIntent(
            intent="clarification_required",
            parameters=extracted,
            query=str(query or ""),
            decomposition=decomposition_dict,
            execution_route=execution_route,
        )

    if not decomposition.tasks:
        return RoutedIntent(
            intent="unsupported",
            parameters=extracted,
            query=str(query or ""),
            decomposition=decomposition_dict,
            execution_route=execution_route,
        )

    if decomposition.is_multi_intent:
        return RoutedIntent(
            intent="multi_intent",
            parameters=extracted,
            query=str(query or ""),
            decomposition=decomposition_dict,
            execution_route=execution_route,
        )

    primary = decomposition.primary_task
    if primary is None:
        return RoutedIntent(
            intent="unsupported",
            parameters=extracted,
            query=str(query or ""),
            decomposition=decomposition_dict,
            execution_route=execution_route,
        )

    if primary.capability_status != "executable":
        return RoutedIntent(
            intent="known_not_integrated",
            parameters=_merge_parameters(
                extracted,
                primary.parameters,
            ),
            query=str(query or ""),
            decomposition=decomposition_dict,
            execution_route=execution_route,
        )

    return RoutedIntent(
        intent=primary.intent,
        parameters=_merge_parameters(
            extracted,
            primary.parameters,
        ),
        query=str(query or ""),
        decomposition=decomposition_dict,
        execution_route=execution_route,
    )
