from __future__ import annotations

import asyncio
from dataclasses import replace
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.console_trace import flow_event, trace_event, trace_exception

from agent.schemas import AgentStepStatus, AgentTaskStatus
from agent.orchestration.argument_resolver import (
    resolve_task_arguments,
)
from agent.orchestration.result_aggregator import (
    aggregate_multi_task_answer,
)
from agent.tools.tool_registry import get_tool_registry, validate_tool_args
from agent.artifacts import artifact_cache_key
from agent.tool_engine import AGENT_MAIN, AGENT_READ, OP_PROPOSAL, OP_READ, OP_SYSTEM, execute_tool_legacy_dict, get_tool_registry_v2
from agent.intent_decomposition.schemas import WRITE_INTENTS
from agent.mcp.registry_bridge import (
    get_mcp_tool_spec,
    is_mcp_tool_name,
    mcp_call_metadata,
)
from agent.mcp.schema_adapter import validate_arguments as validate_mcp_arguments
from agent.runtime_reliability import (
    CircuitBreakerRegistry,
    RuntimeBudget,
    RuntimeCircuitOpen,
    RuntimePolicy,
    classify_runtime_error,
    execute_with_policy,
)
from agent.replan_execution import ensure_replan_state


READ_ONLY_MULTI_INTENTS = {
    "ranking",
    "stock_lookup",
    "classic_stock_score",
    "classic_ranking",
    "portfolio_state",
    "portfolio_risk",
    "portfolio.get_state",
    "portfolio.get_account_summary",
    "portfolio.get_positions",
    "portfolio.get_orders",
    "portfolio.analyze_risk",
    "portfolio.compare_risk_before_after",
    "portfolio.design_target_portfolio",
    "portfolio.construct_target_portfolio",
    "portfolio.load_target_portfolio",
    "portfolio.compare_portfolios",
    "stock_analysis",
    "market.compare_stocks",
    "market.get_signal_summary",
    "stock_news",
    "stock_rag",
    "news_search",
    "rag_search",
    "evidence.search_news",
    "evidence.search_rag",
    "evidence.get_stock_evidence",
    "evidence.get_market_evidence",
    "evidence.mcp_readonly_evidence",
    "mcp_market_risk_summary",
    "position_recommendation",
    "replacement_recommendation",
    "user_profile",
    "scheduler_status",
    "python_sandbox_analysis",
    "report",
    "report_latest",
    "mcp_tool",
}


def _is_read_only_multi_intent(intent: str) -> bool:
    name = str(intent or "")
    return name in READ_ONLY_MULTI_INTENTS or is_mcp_tool_name(name)

PROTECTED_MULTI_INTENTS = {
    "preview_add_stock",
    "adjust_position",
    "one_time_position_operation",
    "strategy_change",
    "confirm_execute",
    "capital_management",
    "backfill",
}

STOCK_CODE_REQUIRED = {
    "stock_analysis",
    "stock_news",
    "stock_rag",
    "position_recommendation",
    "replacement_recommendation",
    "adjust_position",
}

MAX_BATCH_ITEMS = 20
MAX_CONCURRENT_READS = 4
MAX_STEP_RETRIES = 2
STEP_TIMEOUT_SECONDS = 30.0
RETRY_BACKOFF_SECONDS = 0.15
MAX_REPLAN_ROUNDS = 2
MAX_REPLAN_NEW_STEPS = 5


def _estimate_tokens(value: Any) -> int:
    return max(1, len(str(value or "")) // 4)


def _policy_from_context(context: dict[str, Any] | None) -> RuntimePolicy:
    raw = (context or {}).get("runtime_policy")
    if isinstance(raw, RuntimePolicy):
        return raw
    if isinstance(raw, dict):
        allowed = set(RuntimePolicy.__dataclass_fields__)
        values = {key: value for key, value in raw.items() if key in allowed}
        try:
            return RuntimePolicy.default()._resolve(values)
        except Exception:
            return RuntimePolicy.default()
    return RuntimePolicy.default()


def _normalise_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if "." in text:
        parts = text.split(".")
        numeric = next(
            (
                part
                for part in parts
                if part.isdigit()
            ),
            "",
        )
        if numeric:
            text = numeric
    digits = "".join(
        char for char in text if char.isdigit()
    )
    return digits[-6:].zfill(6) if digits else ""


def _normalise_result(
    raw: Any,
    *,
    tool_name: str,
) -> dict[str, Any]:
    if hasattr(raw, "to_dict"):
        data = raw.to_dict()
    elif isinstance(raw, dict):
        data = dict(raw)
    else:
        data = {
            "success": True,
            "message": str(raw),
            "data": {},
        }

    if "success" in data:
        success = bool(data.get("success"))
    elif str(data.get("status") or "").lower() in {
        "success",
        "ok",
    }:
        success = True
    elif str(data.get("status") or "").lower().startswith(
        "missing"
    ):
        success = False
    else:
        success = not bool(data.get("errors"))

    nested_data = data.get("data")
    if not isinstance(nested_data, dict):
        nested_data = {
            key: value
            for key, value in data.items()
            if key not in {
                "success",
                "message",
                "warnings",
                "errors",
                "tool_name",
                "permission",
                "disclaimer",
            }
        }

    warnings = data.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = [str(warnings)]

    errors = data.get("errors") or []
    if not isinstance(errors, list):
        errors = [str(errors)]

    return {
        "success": success,
        "message": str(data.get("message") or ""),
        "data": nested_data,
        "warnings": [
            str(item)
            for item in warnings
            if str(item).strip()
        ],
        "errors": [
            str(item)
            for item in errors
            if str(item).strip()
        ],
        "tool_name": str(
            data.get("tool_name") or tool_name
        ),
    }


def _filter_arguments(
    intent: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    if is_mcp_tool_name(intent):
        return dict(arguments or {})

    allowed = {
        "ranking": {
            "stock_code",
            "top_k",
            "model_name",
        },
        "stock_lookup": {
            "user_id",
            "stock_query",
            "stock_code",
        },
        "classic_stock_score": {
            "user_id",
            "stock_query",
            "stock_code",
        },
        "classic_ranking": {
            "user_id",
            "sort_by",
        },
        "market.compare_stocks": {
            "user_id",
            "stock_codes",
            "stock_code",
            "top_k",
        },
        "market.get_signal_summary": {
            "user_id",
            "sort_by",
        },
        "portfolio_state": {
            "user_id",
        },
        "portfolio_risk": {
            "user_id",
        },
        "portfolio.get_state": {
            "user_id",
        },
        "portfolio.get_account_summary": {
            "user_id",
        },
        "portfolio.get_positions": {
            "user_id",
        },
        "portfolio.get_orders": {
            "user_id",
        },
        "portfolio.analyze_risk": {
            "user_id",
        },
        "portfolio.compare_risk_before_after": {
            "user_id",
            "before",
            "after",
        },
        "portfolio.design_target_portfolio": {
            "current_portfolio",
            "ranking",
            "risk_report",
            "user_profile",
            "query",
            "user_goal",
            "construction_feedback",
        },
        "portfolio.construct_target_portfolio": {
            "user_id",
            "current_portfolio",
            "ranking",
            "risk_report",
            "user_profile",
            "target_design",
            "target_position_count",
            "target_cash_weight",
            "candidate_policy",
            "allocation_method",
            "max_single_weight",
            "max_industry_weight",
        },
        "portfolio.load_target_portfolio": {
            "user_id",
            "conversation_id",
            "artifact_id",
        },
        "portfolio.compare_portfolios": {
            "current_portfolio",
            "target_portfolio",
        },
        "stock_analysis": {
            "user_id",
            "stock_code",
            "as_of_date",
            "top_k",
            "include_rag",
        },
        "stock_news": {
            "stock_code",
            "as_of_date",
            "limit",
            "top_k",
        },
        "stock_rag": {
            "stock_code",
            "query",
            "top_k",
        },
        "news_search": {
            "stock_code",
            "as_of_date",
            "limit",
            "top_k",
        },
        "rag_search": {
            "stock_code",
            "query",
            "top_k",
        },
        "evidence.search_news": {
            "stock_code",
            "as_of_date",
            "limit",
            "top_k",
        },
        "evidence.search_rag": {
            "stock_code",
            "query",
            "top_k",
        },
        "evidence.get_stock_evidence": {
            "stock_code",
            "query",
            "as_of_date",
            "top_k",
        },
        "evidence.get_market_evidence": {
            "query",
            "stock_codes",
            "stock_code",
            "as_of_date",
            "top_k",
        },
        "evidence.mcp_readonly_evidence": {
            "mcp_tool_name",
            "tool_name",
            "arguments",
        },
        "mcp_market_risk_summary": {
            "mcp_tool_name",
            "tool_name",
            "arguments",
        },
        "position_recommendation": {
            "user_id",
            "stock_code",
            "requested_weight",
            "top_k",
        },
        "replacement_recommendation": {
            "user_id",
            "stock_code",
            "requested_weight",
        },
        "user_profile": {
            "user_id",
        },
        "adjust_position": {
            "user_id",
            "stock_code",
            "requested_weight",
            "position_adjustment_ratio",
            "requested_quantity",
            "top_k",
        },
        "scheduler_status": set(),
        "python_sandbox_analysis": {
            "code",
            "snapshot",
            "snapshot_id",
            "timeout_seconds",
            "max_output_chars",
        },
        "report": set(),
        "report_latest": set(),
        "mcp_tool": {
            "mcp_tool_name",
            "tool_name",
            "arguments",
        },
    }

    fields = allowed.get(intent, set())
    return {
        key: value
        for key, value in arguments.items()
        if key in fields
    }


def _execute_single(
    intent: str,
    arguments: dict[str, Any],
    *,
    output_dir: str | Path,
    db_path: str | Path | None,
    default_top_k: int,
    execution_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    args = _filter_arguments(intent, arguments)
    trace_event(
        "dag.task.execute.start",
        {"intent": intent, "arguments": args},
        run_id=str((execution_context or {}).get("run_id") or ""),
        task_id=str((execution_context or {}).get("task_id") or ""),
    )
    is_dynamic_mcp = is_mcp_tool_name(intent)
    v2_intent = "mcp.readonly.invoke" if is_dynamic_mcp else intent
    v2_args = {"mcp_tool_name": intent, "arguments": args} if is_dynamic_mcp else args
    tool_definition = get_tool_registry_v2().get(v2_intent)
    if tool_definition is not None and tool_definition.operation_type in {OP_READ, OP_PROPOSAL, OP_SYSTEM}:
        agent_type = AGENT_READ if tool_definition.operation_type == OP_READ else AGENT_MAIN
        tool_policy = None
        if is_dynamic_mcp:
            runtime_policy = _policy_from_context(execution_context)
            overrides = dict(runtime_policy.tool_overrides or {})
            if intent in overrides and "mcp.readonly.invoke" not in overrides:
                overrides["mcp.readonly.invoke"] = dict(overrides.get(intent) or {})
            tool_policy = replace(runtime_policy, tool_overrides=overrides)
        result = execute_tool_legacy_dict(
            v2_intent,
            v2_args,
            context={
                **dict(execution_context or {}),
                "output_dir": output_dir,
                "db_path": db_path,
                "default_top_k": default_top_k,
                "user_id": args.get("user_id") or (execution_context or {}).get("user_id") or "default",
            },
            agent_type=agent_type,
            policy=tool_policy,
        )
        if is_dynamic_mcp:
            data = dict(result.get("data") or {})
            data.setdefault("v2_bridge_tool_name", "mcp.readonly.invoke")
            result["data"] = data
            result["tool_name"] = intent
        return result

    if is_mcp_tool_name(intent):
        return {
            "success": False,
            "message": "mcp_readonly_bridge_unavailable",
            "data": {},
            "warnings": [],
            "errors": ["mcp_readonly_bridge_unavailable"],
            "tool_name": intent,
        }

    else:
        return {
            "success": False,
            "message": "unsupported_read_only_intent",
            "data": {},
            "warnings": [],
            "errors": [
                f"unsupported_read_only_intent:{intent}"
            ],
            "tool_name": intent,
        }


def _topological_order(
    tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {
        str(task.get("task_id") or ""): task
        for task in tasks
        if str(task.get("task_id") or "")
    }
    pending = list(by_id.keys())
    completed: set[str] = set()
    ordered: list[dict[str, Any]] = []

    while pending:
        progressed = False

        for task_id in list(pending):
            task = by_id[task_id]
            dependencies = [
                str(item)
                for item in (
                    task.get("depends_on") or []
                )
            ]

            if all(
                dependency in completed
                for dependency in dependencies
            ):
                ordered.append(task)
                completed.add(task_id)
                pending.remove(task_id)
                progressed = True

        if not progressed:
            raise ValueError(
                "intent_task_dependency_cycle_or_missing_dependency"
            )

    return ordered


def _batch_values(
    intent: str,
    arguments: dict[str, Any],
) -> tuple[str | None, list[Any]]:
    if intent not in STOCK_CODE_REQUIRED:
        return None, []

    stock_codes = arguments.get("stock_code")
    if not isinstance(stock_codes, list):
        return None, []

    normalised = [
        _normalise_code(item)
        for item in stock_codes
    ]
    normalised = [
        item for item in normalised if item
    ]

    unique: list[str] = []
    for item in normalised:
        if item not in unique:
            unique.append(item)

    return "stock_code", unique[:MAX_BATCH_ITEMS]


def _task_failure(
    task: dict[str, Any],
    error: str,
) -> dict[str, Any]:
    return {
        "task_id": str(task.get("task_id") or ""),
        "intent": str(task.get("intent") or ""),
        "success": False,
        "step_status": AgentStepStatus.FAILED,
        "execution_mode": "single",
        "arguments": {},
        "message": "",
        "data": {},
        "items": [],
        "warnings": [],
        "errors": [error],
    }


def _result_payload(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data")
    return data if isinstance(data, dict) else {}


def _has_empty_dependency(result: dict[str, Any]) -> bool:
    data = _result_payload(result)
    intent = str(result.get("intent") or "")
    if intent in {"portfolio_state", "portfolio.get_state", "portfolio.get_positions"}:
        return int(data.get("position_count") or 0) == 0 and not data.get("positions")
    if intent in {"ranking", "market.get_ranking"}:
        return int(data.get("returned_count") or 0) == 0 or not data.get("records")
    if intent == "stock_rag":
        return not data.get("chunks")
    if intent == "stock_news":
        return not data.get("events")
    return False


def _result_schema_errors(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(result.get("success"), bool):
        errors.append("result_success_not_boolean")
    if not isinstance(result.get("data"), dict):
        errors.append("result_data_not_object")
    if not isinstance(result.get("warnings", []), list):
        errors.append("result_warnings_not_array")
    if not isinstance(result.get("errors", []), list):
        errors.append("result_errors_not_array")
    if not str(result.get("intent") or ""):
        errors.append("result_intent_missing")
    return errors


def _result_sources_present(result: dict[str, Any]) -> bool:
    data = _result_payload(result)
    for key in ("records", "positions", "orders", "events", "chunks", "items", "mcp_sources"):
        value = data.get(key)
        if isinstance(value, list) and value:
            return True
    output_paths = data.get("output_paths")
    if isinstance(output_paths, dict) and output_paths:
        return True
    return any(data.get(key) not in (None, "") for key in ("source_file", "source", "snapshot_id", "stock_code"))


def _deterministic_dependency_errors(
    task_results: dict[str, dict[str, Any]],
    tasks_by_id: dict[str, dict[str, Any]] | None,
) -> list[str]:
    if not tasks_by_id:
        return []
    errors: list[str] = []
    for task_id, task in tasks_by_id.items():
        dependencies = [str(item) for item in (task.get("depends_on") or [])]
        for dependency in dependencies:
            if dependency not in task_results:
                errors.append(f"dependency_missing:{task_id}:{dependency}")
    return errors


def _validate_v2_call_arguments(definition: Any, arguments: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    schema = definition.input_schema if isinstance(getattr(definition, "input_schema", None), dict) else {}
    for name in schema.get("required") or []:
        if arguments.get(name) in (None, ""):
            errors.append(f"missing_required:{name}")
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    type_map: dict[str, Any] = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    for name, value in arguments.items():
        if value is None or name not in properties:
            continue
        expected = str((properties.get(name) or {}).get("type") or "")
        allowed = type_map.get(expected)
        if allowed and not isinstance(value, allowed):
            errors.append(f"invalid_type:{name}:{expected}")
    return errors


def _tool_permission_errors(
    tool_calls: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
) -> list[str]:
    """Audit read-only calls against the same v2 registry used for execution.

    The previous implementation only checked the legacy registry, which caused
    canonical LLM-planned capabilities such as portfolio.design_target_portfolio
    to be reported as unregistered after they had already executed successfully.
    """

    legacy_registry = get_tool_registry()
    v2_registry = get_tool_registry_v2()
    errors: list[str] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        tool_name = str(call.get("tool_name") or "")
        if not tool_name:
            continue
        arguments = dict(call.get("arguments") or {})

        v2_definition = v2_registry.get(tool_name)
        if v2_definition is not None:
            if v2_definition.operation_type != OP_READ:
                errors.append(f"non_read_tool_in_readonly_orchestration:{tool_name}")
            argument_errors = _validate_v2_call_arguments(v2_definition, arguments)
            if argument_errors:
                errors.append(f"tool_args_invalid:{tool_name}:{','.join(argument_errors)}")
            continue

        spec = legacy_registry.get(tool_name) or get_mcp_tool_spec(tool_name, context)
        if spec is None:
            errors.append(f"tool_not_registered:{tool_name}")
            continue
        if not spec.read_only:
            errors.append(f"non_read_tool_in_readonly_orchestration:{tool_name}")
        if is_mcp_tool_name(tool_name):
            ok, arg_errors = validate_mcp_arguments(spec.input_schema, arguments)
        else:
            ok, arg_errors = validate_tool_args(tool_name, arguments)
        if not ok and arg_errors:
            errors.append(f"tool_args_invalid:{tool_name}:{','.join(arg_errors)}")
    return errors


def _semantic_observer_trigger_reasons(
    task_results: dict[str, dict[str, Any]],
    observation: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    intents: dict[str, list[dict[str, Any]]] = {}
    for result in task_results.values():
        intents.setdefault(str(result.get("intent") or ""), []).append(result)

    for intent, rows in intents.items():
        statuses = {bool(row.get("success")) for row in rows}
        if len(rows) > 1 and len(statuses) > 1:
            reasons.append(f"agent_result_conflict:{intent}")

    if observation.get("missing_information"):
        reasons.append("missing_requested_key_information")

    schema_errors = observation.get("schema_errors") or []
    if schema_errors:
        reasons.append("output_schema_incomplete")

    evidence_required = any(
        str(result.get("intent") or "") in {"stock_rag", "stock_news"}
        or is_mcp_tool_name(str(result.get("intent") or ""))
        for result in task_results.values()
    )
    evidence_present = any(
        (
            str(result.get("intent") or "") in {"stock_rag", "stock_news"}
            or is_mcp_tool_name(str(result.get("intent") or ""))
        )
        and _result_sources_present(result)
        for result in task_results.values()
    )
    if evidence_required and not evidence_present:
        reasons.append("evidence_conclusion_mismatch")

    complex_complete = len(task_results) >= 3 and bool(observation.get("goal_satisfied"))
    if complex_complete:
        reasons.append("complex_multi_intent_completeness_check")

    return list(dict.fromkeys(reasons))


def _run_semantic_observer(
    task_results: dict[str, dict[str, Any]],
    observation: dict[str, Any],
    trigger_reasons: list[str],
) -> dict[str, Any]:
    failed_steps = list(observation.get("failed_steps") or [])
    missing_information = list(observation.get("missing_information") or [])
    conflict = any(str(item).startswith("agent_result_conflict") for item in trigger_reasons)
    partial = bool(failed_steps) or bool(missing_information)
    complete = bool(task_results) and not partial and not conflict
    replan_suggestion = ""
    if missing_information:
        replan_suggestion = "add_or_replace_readonly_evidence_task"
    elif conflict:
        replan_suggestion = "replace_conflicting_readonly_task"
    return {
        "complete": complete,
        "partial": partial,
        "conflict": conflict,
        "replan_suggestion": replan_suggestion,
        "missing_information": missing_information,
        "confidence": 0.72 if (partial or conflict) else 0.86,
    }


def _observe_task_results(
    task_results: dict[str, dict[str, Any]],
    *,
    replan_count: int,
    replan_limit: int,
    tasks_by_id: dict[str, dict[str, Any]] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    budget: RuntimeBudget | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failed_steps = [
        {
            "task_id": task_id,
            "intent": result.get("intent"),
            "errors": list(result.get("errors") or []),
        }
        for task_id, result in task_results.items()
        if not result.get("success")
        and result.get("step_status") != AgentStepStatus.SKIPPED
    ]
    missing_information: list[str] = []
    for item in failed_steps:
        for error in item.get("errors") or []:
            if "missing_stock_code" in str(error):
                missing_information.append("stock_code")

    available_results = [
        {
            "task_id": task_id,
            "intent": result.get("intent"),
            "step_status": result.get("step_status"),
        }
        for task_id, result in task_results.items()
        if result.get("success")
    ]
    has_pending_approval = any(
        bool((_result_payload(result)).get("plan_id"))
        for result in task_results.values()
    )
    schema_errors: list[str] = []
    source_checks: list[dict[str, Any]] = []
    for task_id, result in task_results.items():
        for error in _result_schema_errors(result):
            schema_errors.append(f"{task_id}:{error}")
        source_checks.append(
            {
                "task_id": task_id,
                "intent": result.get("intent"),
                "sources_present": _result_sources_present(result),
            }
        )
    dependency_errors = _deterministic_dependency_errors(task_results, tasks_by_id)
    permission_errors = _tool_permission_errors(list(tool_calls or []), context=context)
    budget_usage = budget.to_dict() if budget is not None else {}
    plan_ids = [
        str(_result_payload(result).get("plan_id") or "")
        for result in task_results.values()
        if _result_payload(result).get("plan_id")
    ]
    partial_results = any(result.get("success") for result in task_results.values()) and bool(failed_steps)
    goal_satisfied = bool(task_results) and not failed_steps
    next_action = "finish"
    if has_pending_approval:
        next_action = "wait_approval"
    elif (failed_steps or schema_errors or dependency_errors) and replan_count < replan_limit:
        next_action = "replan"
    observation = {
        "goal_satisfied": goal_satisfied,
        "missing_information": sorted(set(missing_information)),
        "failed_steps": failed_steps,
        "available_results": available_results,
        "next_action": next_action,
        "replan_count": replan_count,
        "replan_limit": replan_limit,
        "observe_layer": "deterministic",
        "tool_status": {
            "success_count": sum(1 for result in task_results.values() if result.get("success")),
            "failed_count": len(failed_steps),
            "tool_call_count": len(tool_calls or []),
        },
        "schema_valid": not schema_errors,
        "schema_errors": schema_errors,
        "dependencies_satisfied": not dependency_errors,
        "dependency_errors": dependency_errors,
        "sources": source_checks,
        "permission_budget": {
            "permission_valid": not permission_errors,
            "permission_errors": permission_errors,
            "budget": budget_usage,
        },
        "proposal_plan_ids": plan_ids,
        "plan_id_valid": all(bool(item) for item in plan_ids),
        "partial_results": partial_results,
    }
    trigger_reasons = _semantic_observer_trigger_reasons(task_results, observation)
    observation["semantic_observer"] = {
        "triggered": bool(trigger_reasons),
        "trigger_reasons": trigger_reasons,
        "result": (
            _run_semantic_observer(task_results, observation, trigger_reasons)
            if trigger_reasons
            else {}
        ),
    }
    return observation


def _apply_terminal_replan_for_empty_dependencies(
    task_results: dict[str, dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
) -> tuple[bool, list[str]]:
    changed = False
    warnings: list[str] = []
    for task_id, result in list(task_results.items()):
        if result.get("success"):
            continue
        errors = [str(item) for item in (result.get("errors") or [])]
        if "missing_stock_code" not in errors:
            continue
        task = by_id.get(task_id) or {}
        dependencies = [str(item) for item in (task.get("depends_on") or [])]
        empty_dependencies = [
            dependency
            for dependency in dependencies
            if _has_empty_dependency(task_results.get(dependency, {}))
        ]
        if not empty_dependencies:
            continue
        result["step_status"] = AgentStepStatus.SKIPPED
        result["execution_mode"] = "terminal_replan_skip"
        result["message"] = "Skipped because the dependency result was empty."
        result["warnings"] = list(result.get("warnings") or []) + [
            "terminal_replan_empty_dependency:" + ",".join(empty_dependencies)
        ]
        result["errors"] = []
        task_results[task_id] = result
        warnings.append(f"{task_id} skipped because dependency result was empty.")
        changed = True
    return changed, warnings


def _stock_rag_needs_news_replan(result: dict[str, Any]) -> bool:
    if str(result.get("intent") or "") != "stock_rag":
        return False
    data = _result_payload(result)
    if data.get("chunks"):
        return False
    status = str(data.get("status") or "").lower()
    return status in {"no_rag_chunks", "unavailable", "invalid_stock_code", ""}


def _make_stock_news_replan_task(
    source_task_id: str,
    source_result: dict[str, Any],
    index: int,
) -> dict[str, Any] | None:
    arguments = dict(source_result.get("arguments") or {})
    data = _result_payload(source_result)
    stock_code = arguments.get("stock_code") or data.get("stock_code")
    if not stock_code:
        items = data.get("items")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_data = item.get("data") if isinstance(item.get("data"), dict) else {}
                if item_data.get("chunks"):
                    continue
                item_args = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
                stock_code = item_args.get("stock_code") or item_data.get("stock_code")
                if stock_code:
                    break
    if not stock_code:
        return None
    return {
        "task_id": f"replan_{index}_stock_news",
        "intent": "stock_news",
        "parameters": {"stock_code": stock_code},
        "depends_on": [source_task_id],
        "reason": "RAG returned no chunks; use mapped stock news as a read-only fallback.",
        "capability_status": "executable",
    }


def _mcp_needs_local_fallback(result: dict[str, Any]) -> bool:
    intent = str(result.get("intent") or "")
    if not is_mcp_tool_name(intent):
        return False
    data = _result_payload(result)
    if not result.get("success"):
        return True
    if data.get("mcp_sources") or data.get("records") or data.get("items"):
        return False
    return True


def _make_mcp_local_fallback_task(
    source_task_id: str,
    source_result: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    arguments = dict(source_result.get("arguments") or {})
    top_k = arguments.get("top_k") or 10
    return {
        "task_id": f"replan_{index}_local_ranking",
        "intent": "ranking",
        "parameters": {"top_k": top_k},
        "depends_on": [source_task_id],
        "reason": "MCP evidence failed or was insufficient; use local ranking as a read-only fallback.",
        "capability_status": "executable",
    }


def _dag_snapshot(tasks_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "task_id": task_id,
            "intent": str(task.get("intent") or ""),
            "depends_on": [str(item) for item in (task.get("depends_on") or [])],
        }
        for task_id, task in sorted(tasks_by_id.items())
    ]


def _validate_replan_candidates(
    candidates: list[dict[str, Any]],
    *,
    tasks_by_id: dict[str, dict[str, Any]],
    budget: RuntimeBudget,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    if budget.tool_budget_exhausted:
        return [], [
            {
                "task_id": str(task.get("task_id") or ""),
                "intent": str(task.get("intent") or ""),
                "reason": "budget_hard_limit",
            }
            for task in candidates
        ]

    for task in candidates:
        task_id = str(task.get("task_id") or "")
        intent = str(task.get("intent") or "")
        parameters = dict(task.get("parameters") or {})
        dependencies = [str(item) for item in (task.get("depends_on") or [])]
        reason = ""
        if not task_id or task_id in tasks_by_id:
            reason = "invalid_or_duplicate_task_id"
        elif intent in WRITE_INTENTS or intent in PROTECTED_MULTI_INTENTS:
            reason = "write_task_not_allowed_in_replan"
        elif not _is_read_only_multi_intent(intent):
            reason = "unsupported_replan_intent"
        elif any(item not in tasks_by_id for item in dependencies):
            reason = "missing_replan_dependency"
        elif any(key in parameters for key in ("plan_id", "confirmation_token", "proposal_id")):
            reason = "proposal_mutation_not_allowed"
        if reason:
            blocked.append({"task_id": task_id, "intent": intent, "reason": reason})
        else:
            accepted.append(dict(task))
    return accepted, blocked


_READONLY_REPLAN_ACTIONS = {
    "replan",
    "replan_readonly",
    "replan_target_design",
    "retry_readonly",
}

_READONLY_REPLAN_ERRORS = {
    "missing_llm_target_design_or_sources",
    "invalid_llm_target_design",
    "llm_target_design_not_constructible",
    "missing_required_sources",
    "target_design_requires_replan",
}


def _replan_directive(result: dict[str, Any]) -> tuple[bool, str]:
    """Return a bounded replan directive from structured task feedback.

    Business semantics are not inferred here. A task must explicitly mark the
    failure as repairable and request replan, or use one of the generic read-only
    recovery actions. Non-repairable system/data failures are never retried.
    """

    data = _result_payload(result)
    action = str(
        data.get("next_action")
        or result.get("next_action")
        or ""
    ).strip().lower()
    if bool(data.get("no_automatic_replan")):
        return False, action
    if data.get("repairable") is False:
        return False, action

    requested = bool(data.get("replan_required")) or action in _READONLY_REPLAN_ACTIONS
    if not requested:
        errors = {
            str(item).split(":", 1)[0]
            for item in (result.get("errors") or [])
        }
        requested = bool(errors & _READONLY_REPLAN_ERRORS) and data.get("repairable") is not False
    return requested, action


def _task_descendants(
    source_task_id: str,
    tasks_by_id: dict[str, dict[str, Any]],
) -> set[str]:
    affected = {str(source_task_id)}
    changed = True
    while changed:
        changed = False
        for task_id, task in tasks_by_id.items():
            dependencies = {
                str(item)
                for item in (task.get("depends_on") or [])
            }
            if task_id not in affected and dependencies & affected:
                affected.add(task_id)
                changed = True
    return affected


def _design_dependency_for_replan(
    failed_task_id: str,
    result: dict[str, Any],
    tasks_by_id: dict[str, dict[str, Any]],
) -> str:
    """Choose the smallest LLM-owned source task for a structured redesign.

    The decision is driven by replan_scope/next_action emitted by the failed
    task, not by problem-specific status strings.
    """

    data = _result_payload(result)
    _, action = _replan_directive(result)
    scope = str(data.get("replan_scope") or "").strip().lower()
    wants_design = scope in {"target_design", "design"} or action == "replan_target_design"
    if not wants_design:
        return failed_task_id

    failed_task = tasks_by_id.get(failed_task_id) or {}
    if str(failed_task.get("intent") or "") == "portfolio.design_target_portfolio":
        return failed_task_id
    for dependency in failed_task.get("depends_on") or []:
        dependency_id = str(dependency)
        dependency_task = tasks_by_id.get(dependency_id) or {}
        if str(dependency_task.get("intent") or "") == "portfolio.design_target_portfolio":
            return dependency_id
    return failed_task_id


def _retry_task_with_feedback(
    task: dict[str, Any],
    *,
    failed_task_id: str,
    failed_result: dict[str, Any],
    round_index: int,
) -> dict[str, Any]:
    retry = dict(task)
    parameters = dict(retry.get("parameters") or {})
    if str(retry.get("intent") or "") == "portfolio.design_target_portfolio":
        parameters["construction_feedback"] = {
            "source_failed_task_id": failed_task_id,
            "failure_status": str(
                _result_payload(failed_result).get("status")
                or failed_result.get("status")
                or ""
            ),
            "failure_data": _result_payload(failed_result),
            "failure_errors": list(failed_result.get("errors") or []),
            "replan_round": round_index,
            "instruction": (
                "Reuse successful dependency results and correct only the structured validation failures. "
                "Return a complete replacement target_design, not a patch. Preserve valid business decisions "
                "when possible, but satisfy the original user goal and every validation item. Do not invent "
                "missing source data and do not ask for information already present."
            ),
        }
    retry["parameters"] = parameters
    retry["reason"] = (
        str(retry.get("reason") or "")
        + f" [bounded read-only recovery round {round_index}]"
    ).strip()
    return retry


def _select_readonly_replan_candidate(
    task_results: dict[str, dict[str, Any]],
    tasks_by_id: dict[str, dict[str, Any]],
    attempted: set[str],
) -> tuple[str, str, dict[str, Any], str] | None:
    for failed_task_id, result in task_results.items():
        if result.get("success") or result.get("step_status") == AgentStepStatus.SKIPPED:
            continue
        requested, action = _replan_directive(result)
        if not requested:
            continue
        failed_task = tasks_by_id.get(failed_task_id) or {}
        if not _is_read_only_multi_intent(str(failed_task.get("intent") or "")):
            continue

        source_task_id = _design_dependency_for_replan(
            failed_task_id,
            result,
            tasks_by_id,
        )
        source_task = tasks_by_id.get(source_task_id) or {}
        if not _is_read_only_multi_intent(str(source_task.get("intent") or "")):
            continue
        dependencies = [
            str(item)
            for item in (source_task.get("depends_on") or [])
        ]
        if any(
            dependency not in task_results
            or not task_results[dependency].get("success")
            for dependency in dependencies
        ):
            continue

        fingerprint = "|".join(
            [
                source_task_id,
                failed_task_id,
                action,
                str(_result_payload(result).get("status") or ""),
                ",".join(sorted(str(item) for item in (result.get("errors") or []))),
            ]
        )
        if fingerprint in attempted:
            continue
        return source_task_id, failed_task_id, result, fingerprint
    return None


async def _execute_replan_subgraph(
    affected: set[str],
    *,
    tasks_by_id: dict[str, dict[str, Any]],
    task_results: dict[str, dict[str, Any]],
    execution_context: dict[str, Any],
    output_dir: str | Path,
    db_path: str | Path | None,
    default_top_k: int,
    semaphore: asyncio.Semaphore,
    timeout_seconds: float,
    max_retries: int,
    policy: RuntimePolicy,
    budget: RuntimeBudget,
    circuit_registry: CircuitBreakerRegistry,
    execution_batches: list[list[str]],
    tool_calls: list[dict[str, Any]],
    global_warnings: list[str],
) -> None:
    pending = set(affected)
    while pending:
        ready = [
            task_id
            for task_id in sorted(pending)
            if all(
                str(dependency) in task_results
                for dependency in (
                    tasks_by_id.get(task_id, {}).get("depends_on") or []
                )
            )
        ]
        if not ready:
            global_warnings.append(
                "readonly_replan_dependency_cycle_or_missing_dependency"
            )
            return

        runnable: list[dict[str, Any]] = []
        for task_id in ready:
            task = tasks_by_id[task_id]
            dependencies = [
                str(item)
                for item in (task.get("depends_on") or [])
            ]
            failed_dependencies = [
                dependency
                for dependency in dependencies
                if not task_results.get(dependency, {}).get("success", False)
            ]
            pending.remove(task_id)
            if failed_dependencies:
                result = _task_failure(
                    task,
                    "dependency_failed:" + ",".join(failed_dependencies),
                )
                result.update(
                    {
                        "step_status": AgentStepStatus.SKIPPED,
                        "started_at": _now_iso(),
                        "finished_at": _now_iso(),
                        "duration_seconds": 0.0,
                    }
                )
                task_results[task_id] = result
                continue
            runnable.append(task)

        if not runnable:
            continue
        execution_batches.append(
            [str(task.get("task_id") or "") for task in runnable]
        )
        batch_results = await asyncio.gather(
            *(
                _execute_task_async(
                    task,
                    task_results=task_results,
                    execution_context=execution_context,
                    output_dir=output_dir,
                    db_path=db_path,
                    default_top_k=default_top_k,
                    semaphore=semaphore,
                    timeout_seconds=timeout_seconds,
                    max_retries=max_retries,
                    policy=policy,
                    budget=budget,
                    circuit_registry=circuit_registry,
                )
                for task in runnable
            ),
            return_exceptions=False,
        )
        for task_id, result, calls, warnings in batch_results:
            task_results[task_id] = result
            tool_calls.extend(calls)
            global_warnings.extend(warnings)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _classify_error(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "interface_timeout"
    if isinstance(exc, (TypeError, ValueError)):
        return "parameter_error"
    return "unknown_error"


async def _execute_single_with_retry_async(
    intent: str,
    arguments: dict[str, Any],
    *,
    output_dir: str | Path,
    db_path: str | Path | None,
    default_top_k: int,
    semaphore: asyncio.Semaphore,
    timeout_seconds: float,
    max_retries: int,
    policy: RuntimePolicy,
    budget: RuntimeBudget,
    circuit_registry: CircuitBreakerRegistry,
    execution_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del timeout_seconds, max_retries

    try:
        async with semaphore:
            result, metadata = await asyncio.to_thread(
                execute_with_policy,
                lambda: _execute_single(
                    intent,
                    arguments,
                    output_dir=output_dir,
                    db_path=db_path,
                    default_top_k=default_top_k,
                    execution_context=execution_context,
                ),
                tool_name=intent,
                read_only=True,
                policy=policy,
                budget=budget,
                circuit_registry=circuit_registry,
                token_estimate=0,
                tool_payload_estimate=_estimate_tokens(arguments),
            )
            result = dict(result)
            outer_reliability = metadata.to_dict()
            inner_reliability = dict(result.get("runtime_reliability") or {})
            if inner_reliability.get("error_type"):
                inner_reliability.setdefault("outer_tool_name", outer_reliability.get("tool_name"))
                inner_reliability.setdefault("outer_elapsed_ms", outer_reliability.get("elapsed_ms"))
                result["runtime_reliability"] = inner_reliability
            else:
                result["runtime_reliability"] = outer_reliability
            return result
    except RuntimeCircuitOpen as exc:
        return {
            "success": False,
            "message": "Tool circuit is open; returned a degraded result.",
            "data": {"status": "degraded", "tool_name": intent},
            "warnings": [f"circuit_open:{intent}"],
            "errors": [f"circuit_open:{intent}"],
            "tool_name": intent,
            "runtime_reliability": getattr(exc, "runtime_metadata", None) or {
                "tool_name": intent,
                "error_type": "dependency",
                "circuit_state": circuit_registry.state(intent),
                "budget_usage": budget.to_dict(),
            },
        }
    except Exception as exc:
        reliability = getattr(exc, "runtime_metadata", None)
        error_type = classify_runtime_error(exc)
        return {
            "success": False,
            "message": "",
            "data": {},
            "warnings": [],
            "errors": [f"{error_type}:{type(exc).__name__}:{exc}"],
            "tool_name": intent,
            "runtime_reliability": reliability
            or {
                "tool_name": intent,
                "error_type": error_type,
                "budget_usage": budget.to_dict(),
                "circuit_state": circuit_registry.state(intent),
            },
        }



def _emit_task_result_flow(
    task: dict[str, Any],
    result: dict[str, Any],
    *,
    run_id: str,
) -> None:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    flow_event(
        "TASK_RESULT",
        {
            "task_id": str(task.get("task_id") or ""),
            "capability": str(task.get("intent") or ""),
            "purpose": str(task.get("reason") or ""),
            "success": bool(result.get("success")),
            "step_status": str(result.get("step_status") or ""),
            "execution_mode": str(result.get("execution_mode") or ""),
            "message": str(result.get("message") or ""),
            "produced_output_keys": sorted(data.keys()),
            "produced_outputs": data,
            "warnings": list(result.get("warnings") or []),
            "errors": list(result.get("errors") or []),
            "duration_seconds": result.get("duration_seconds"),
        },
        run_id=run_id,
        task_id=str(task.get("task_id") or ""),
        level="INFO" if result.get("success") else "WARNING",
    )

async def _execute_task_async(
    task: dict[str, Any],
    *,
    task_results: dict[str, dict[str, Any]],
    execution_context: dict[str, Any],
    output_dir: str | Path,
    db_path: str | Path | None,
    default_top_k: int,
    semaphore: asyncio.Semaphore,
    timeout_seconds: float,
    max_retries: int,
    policy: RuntimePolicy,
    budget: RuntimeBudget,
    circuit_registry: CircuitBreakerRegistry,
) -> tuple[str, dict[str, Any], list[dict[str, Any]], list[str]]:
    task_id = str(task.get("task_id") or "")
    intent = str(task.get("intent") or "")
    started_at = _now_iso()
    started_perf = time.perf_counter()
    tool_calls: list[dict[str, Any]] = []
    warnings: list[str] = []
    task_policy = policy
    if intent == "ranking" and "MCP evidence failed" in str(task.get("reason") or ""):
        task_policy = policy._resolve(
            {
                "tool_timeout_seconds": max(float(policy.tool_timeout_seconds), 1.0),
                "max_retry_attempts": max(1, int(policy.max_retry_attempts)),
            }
        )

    registry = get_tool_registry()
    spec = registry.get(intent) or get_mcp_tool_spec(intent, execution_context)
    if spec is not None and (not spec.read_only or not spec.concurrency_safe):
        result = _task_failure(task, "tool_not_allowed_in_read_concurrency_group")
        result.update(
            {
                "step_status": AgentStepStatus.FAILED,
                "started_at": started_at,
                "finished_at": _now_iso(),
                "duration_seconds": round(time.perf_counter() - started_perf, 4),
            }
        )
        return task_id, result, tool_calls, warnings

    arguments = resolve_task_arguments(
        task,
        task_results=task_results,
        context=execution_context,
        default_top_k=default_top_k,
    )
    task_execution_context = {
        **dict(execution_context or {}),
        "task_id": task_id,
        "current_task": dict(task or {}),
        # Shared in-memory budget. Tools that actually call an LLM may record
        # paid model usage here. It is never serialized into the task payload.
        "runtime_budget": budget,
    }
    flow_event(
        "TASK_START",
        {
            "task_id": task_id,
            "capability": intent,
            "purpose": str(task.get("reason") or ""),
            "depends_on": list(task.get("depends_on") or []),
            "expected_outputs": list(task.get("expected_outputs") or []),
            "parameter_sources": dict(task.get("parameters") or {}),
            "resolved_inputs": arguments,
            "next_step": "execute exactly this LLM-planned capability",
        },
        run_id=str(execution_context.get("run_id") or ""),
        task_id=task_id,
    )
    artifact_metrics = execution_context.setdefault(
        "artifact_metrics",
        {
            "artifact_lookup_count": 0,
            "artifact_reuse_count": 0,
            "artifact_ids_used": [],
        },
    )
    artifact_cache = execution_context.setdefault("artifact_result_cache", {})
    cache_key = artifact_cache_key(intent, arguments)
    artifact_metrics["artifact_lookup_count"] = int(artifact_metrics.get("artifact_lookup_count") or 0) + 1
    cached_result = artifact_cache.get(cache_key) if isinstance(artifact_cache, dict) else None
    if isinstance(cached_result, dict):
        artifact_metrics["artifact_reuse_count"] = int(artifact_metrics.get("artifact_reuse_count") or 0) + 1
        artifact_id = str(cached_result.get("artifact_id") or cache_key[:16])
        artifact_ids = list(artifact_metrics.get("artifact_ids_used") or [])
        if artifact_id not in artifact_ids:
            artifact_ids.append(artifact_id)
        artifact_metrics["artifact_ids_used"] = artifact_ids
        finished_at = _now_iso()
        reused = dict(cached_result.get("result") or cached_result)
        result = {
            "task_id": task_id,
            "intent": intent,
            "success": bool(reused.get("success", True)),
            "step_status": AgentStepStatus.SUCCEEDED if reused.get("success", True) else AgentStepStatus.FAILED,
            "execution_mode": "artifact_reuse",
            "arguments": arguments,
            "message": str(reused.get("message") or "Reused prior artifact result."),
            "data": dict(reused.get("data") or {}),
            "items": list(reused.get("items") or []),
            "warnings": list(dict.fromkeys([*list(reused.get("warnings") or []), "artifact_reused"])),
            "errors": list(reused.get("errors") or []),
            "runtime_reliability": dict(reused.get("runtime_reliability") or {}),
            "artifact_reused": True,
            "artifact_id": artifact_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": round(time.perf_counter() - started_perf, 4),
        }
        _emit_task_result_flow(task, result, run_id=str(execution_context.get("run_id") or ""))
        return task_id, result, tool_calls, warnings

    if intent in STOCK_CODE_REQUIRED:
        stock_code_value = arguments.get("stock_code")
        if stock_code_value in (None, "", []):
            result = _task_failure(task, "missing_stock_code")
            result.update(
                {
                    "step_status": AgentStepStatus.FAILED,
                    "started_at": started_at,
                    "finished_at": _now_iso(),
                    "duration_seconds": round(time.perf_counter() - started_perf, 4),
                }
            )
            _emit_task_result_flow(task, result, run_id=str(execution_context.get("run_id") or ""))
            return task_id, result, tool_calls, warnings

    batch_field, batch_items = _batch_values(intent, arguments)
    if batch_field and batch_items:
        async def run_batch_item(value: Any) -> dict[str, Any]:
            item_arguments = dict(arguments)
            item_arguments[batch_field] = value
            item_started = time.perf_counter()
            item_result = await _execute_single_with_retry_async(
                intent,
                item_arguments,
                output_dir=output_dir,
                db_path=db_path,
                default_top_k=default_top_k,
                semaphore=semaphore,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                policy=task_policy,
                budget=budget,
                circuit_registry=circuit_registry,
                execution_context=task_execution_context,
            )
            item_record = {
                    "arguments": {batch_field: value},
                    "duration_seconds": round(time.perf_counter() - item_started, 4),
                    "runtime_reliability": item_result.get("runtime_reliability") or {},
                    **item_result,
                }
            return item_record

        item_results = []
        for value in batch_items:
            item_results.append(await run_batch_item(value))

        for item in item_results:
            tool_calls.append(
                {
                    "task_id": task_id,
                    "tool_name": item.get("tool_name", intent),
                    "success": bool(item.get("success")),
                    "arguments": dict(item.get("arguments") or {}),
                    "runtime_reliability": item.get("runtime_reliability") or {},
                    "mcp": (
                        mcp_call_metadata(
                            tool_name=str(item.get("tool_name") or intent),
                            result=item,
                            runtime_reliability=dict(item.get("runtime_reliability") or {}),
                        )
                        if is_mcp_tool_name(str(item.get("tool_name") or intent))
                        else {}
                    ),
                    "step_status": (
                        AgentStepStatus.SUCCEEDED
                        if item.get("success")
                        else AgentStepStatus.FAILED
                    ),
                }
            )

        success_count = sum(1 for item in item_results if item.get("success"))
        failed_count = len(item_results) - success_count
        task_warnings: list[str] = []
        if failed_count:
            task_warnings.append(f"batch_partial_failure:{failed_count}")
            warnings.append(f"{task_id} 有 {failed_count} 个批量项目执行失败。")

        finished_at = _now_iso()
        result = {
            "task_id": task_id,
            "intent": intent,
            "success": success_count > 0,
            "step_status": AgentStepStatus.SUCCEEDED if success_count > 0 else AgentStepStatus.FAILED,
            "execution_mode": "foreach",
            "arguments": {
                key: value
                for key, value in arguments.items()
                if key != batch_field
            },
            "batch_field": batch_field,
            "batch_count": len(item_results),
            "success_count": success_count,
            "failed_count": failed_count,
            "message": "",
            "data": {"items": item_results},
            "items": item_results,
            "warnings": task_warnings,
            "errors": [] if success_count > 0 else ["all_batch_items_failed"],
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": round(time.perf_counter() - started_perf, 4),
        }
        _emit_task_result_flow(task, result, run_id=str(execution_context.get("run_id") or ""))
        return task_id, result, tool_calls, warnings

    single_result = await _execute_single_with_retry_async(
        intent,
        arguments,
        output_dir=output_dir,
        db_path=db_path,
        default_top_k=default_top_k,
        semaphore=semaphore,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        policy=task_policy,
        budget=budget,
        circuit_registry=circuit_registry,
        execution_context=task_execution_context,
    )
    finished_at = _now_iso()
    if isinstance(artifact_cache, dict):
        artifact_cache[cache_key] = {
            "artifact_id": f"runtime_cache_{cache_key[:16]}",
            "result": dict(single_result),
        }

    result = {
        "task_id": task_id,
        "intent": intent,
        "success": bool(single_result.get("success")),
        "step_status": (
            AgentStepStatus.SUCCEEDED
            if single_result.get("success")
            else AgentStepStatus.FAILED
        ),
        "execution_mode": "single",
        "arguments": arguments,
        "message": single_result.get("message", ""),
        "data": dict(single_result.get("data") or {}),
        "items": [],
        "warnings": list(single_result.get("warnings") or []),
        "errors": list(single_result.get("errors") or []),
        "runtime_reliability": single_result.get("runtime_reliability") or {},
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(time.perf_counter() - started_perf, 4),
    }
    tool_calls.append(
        {
            "task_id": task_id,
            "tool_name": single_result.get("tool_name", intent),
            "success": bool(single_result.get("success")),
            "arguments": arguments,
            "runtime_reliability": single_result.get("runtime_reliability") or {},
            "mcp": (
                mcp_call_metadata(
                    tool_name=str(single_result.get("tool_name") or intent),
                    result=single_result,
                    runtime_reliability=dict(single_result.get("runtime_reliability") or {}),
                )
                if is_mcp_tool_name(str(single_result.get("tool_name") or intent))
                else {}
            ),
            "step_status": result["step_status"],
        }
    )
    _emit_task_result_flow(task, result, run_id=str(execution_context.get("run_id") or ""))
    return task_id, result, tool_calls, warnings


def _run_coroutine_blocking(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(coro)).result()


async def execute_multi_intent_plan_async(
    decomposition: dict[str, Any],
    *,
    user_id: str,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    default_top_k: int = 10,
    session_id: str = "",
    language: str = "zh",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tasks = decomposition.get("tasks") or []
    trace_event(
        "dag.plan.start",
        {"tasks": tasks, "user_goal": decomposition.get("user_goal") or {}, "task_plan": decomposition.get("task_plan") or {}},
        run_id=str((context or {}).get("run_id") or ""),
    )
    flow_event(
        "TASK_PLAN_EXECUTION",
        {
            "user_goal": decomposition.get("user_goal") or {},
            "task_plan": decomposition.get("task_plan") or {"tasks": tasks},
            "exact_tasks_to_execute": tasks,
            "business_task_rewrite_enabled": False,
        },
        run_id=str((context or {}).get("run_id") or ""),
    )
    if not isinstance(tasks, list) or not tasks:
        return {
            "success": False,
            "answer": "",
            "task_results": {},
            "tool_calls": [],
            "warnings": [],
            "errors": ["empty_multi_intent_plan"],
            "execution_status": "rejected",
        }

    protected = [
        str(task.get("intent") or "")
        for task in tasks
        if str(task.get("intent") or "") in PROTECTED_MULTI_INTENTS
    ]
    unsupported = [
        str(task.get("intent") or "")
        for task in tasks
        if not _is_read_only_multi_intent(str(task.get("intent") or ""))
        and str(task.get("intent") or "") not in PROTECTED_MULTI_INTENTS
    ]

    if protected:
        return {
            "success": False,
            "answer": "",
            "task_results": {},
            "tool_calls": [],
            "warnings": [],
            "errors": [
                "protected_multi_intent_requires_separate_confirmation:"
                + ",".join(protected)
            ],
            "execution_status": "rejected",
        }

    if unsupported:
        return {
            "success": False,
            "answer": "",
            "task_results": {},
            "tool_calls": [],
            "warnings": [],
            "errors": ["unsupported_multi_intent:" + ",".join(unsupported)],
            "execution_status": "rejected",
        }

    execution_context = dict(context or {})
    execution_context.setdefault("user_id", user_id)
    execution_context.setdefault("session_id", session_id)
    execution_context.setdefault("default_top_k", default_top_k)
    execution_context.setdefault(
        "artifact_metrics",
        {
            "artifact_lookup_count": 0,
            "artifact_reuse_count": 0,
            "artifact_ids_used": [],
        },
    )
    execution_context.setdefault("artifact_result_cache", {})

    try:
        ordered_tasks = _topological_order(tasks)
        trace_event("dag.plan.topological_order", {"ordered_task_ids": [str(item.get("task_id") or "") for item in ordered_tasks]}, run_id=str(execution_context.get("run_id") or ""))
    except Exception as exc:
        trace_exception("dag.plan.invalid", exc, run_id=str(execution_context.get("run_id") or ""))
        return {
            "success": False,
            "answer": "",
            "task_results": {},
            "tool_calls": [],
            "warnings": [],
            "errors": [f"{type(exc).__name__}:{exc}"],
            "execution_status": "rejected",
        }

    max_concurrency = int(execution_context.get("max_concurrent_reads") or MAX_CONCURRENT_READS)
    max_concurrency = max(1, min(max_concurrency, MAX_CONCURRENT_READS))
    policy = _policy_from_context(execution_context)
    timeout_seconds = float(execution_context.get("step_timeout_seconds") or policy.tool_timeout_seconds or STEP_TIMEOUT_SECONDS)
    max_retries = int(execution_context.get("max_step_retries") or policy.max_retry_attempts or MAX_STEP_RETRIES)
    max_retries = max(0, min(max_retries, int(policy.max_retry_attempts)))
    budget = RuntimeBudget(policy)
    circuit_registry = CircuitBreakerRegistry(policy)
    semaphore = asyncio.Semaphore(max_concurrency)

    by_id = {
        str(task.get("task_id") or ""): task
        for task in ordered_tasks
        if str(task.get("task_id") or "")
    }
    pending = set(by_id)
    task_results: dict[str, dict[str, Any]] = {}
    tool_calls: list[dict[str, Any]] = []
    global_warnings: list[str] = []
    execution_batches: list[list[str]] = []
    observations: list[dict[str, Any]] = []
    replan_state = ensure_replan_state(
        execution_context.get("replan_state") if isinstance(execution_context.get("replan_state"), dict) else None,
        replan_limit=MAX_REPLAN_ROUNDS,
        replan_audit=execution_context.get("replan_audit") if isinstance(execution_context.get("replan_audit"), list) else None,
    )
    execution_context["replan_state"] = replan_state
    replan_audit = replan_state["replan_audit"]
    invalid_replan_block_count = 0
    replan_count = replan_state["replan_count"]
    replan_new_steps = 0

    while pending:
        ready: list[str] = []
        for task_id in sorted(pending):
            dependencies = [str(item) for item in (by_id[task_id].get("depends_on") or [])]
            if all(dependency in task_results for dependency in dependencies):
                ready.append(task_id)

        if not ready:
            return {
                "success": False,
                "answer": "",
                "task_results": task_results,
                "execution_order": [str(task.get("task_id") or "") for task in ordered_tasks],
                "tool_calls": tool_calls,
                "warnings": global_warnings,
                "errors": ["intent_task_dependency_cycle_or_missing_dependency"],
                "execution_status": AgentTaskStatus.FAILED,
            }

        runnable: list[dict[str, Any]] = []
        for task_id in ready:
            task = by_id[task_id]
            dependencies = [str(item) for item in (task.get("depends_on") or [])]
            failed_dependencies = [
                item for item in dependencies if not task_results.get(item, {}).get("success", False)
            ]
            pending.remove(task_id)
            if failed_dependencies:
                result = _task_failure(task, "dependency_failed:" + ",".join(failed_dependencies))
                result.update(
                    {
                        "step_status": AgentStepStatus.SKIPPED,
                        "started_at": _now_iso(),
                        "finished_at": _now_iso(),
                        "duration_seconds": 0.0,
                    }
                )
                task_results[task_id] = result
                continue
            runnable.append(task)

        if not runnable:
            continue

        execution_batches.append([str(task.get("task_id") or "") for task in runnable])
        if budget.tool_budget_exhausted:
            for task in runnable:
                task_id = str(task.get("task_id") or "")
                task_results[task_id] = _task_failure(
                    task,
                    "budget_exceeded:max_tool_calls",
                )
            global_warnings.append("runtime_tool_budget_hard_limit_reached")
            continue
        if budget.llm_budget_exhausted:
            warning = (
                "runtime_llm_budget_exhausted_deterministic_tools_continue"
            )
            if warning not in global_warnings:
                global_warnings.append(warning)
        batch_results = await asyncio.gather(
            *(
                _execute_task_async(
                    task,
                    task_results=task_results,
                    execution_context=execution_context,
                    output_dir=output_dir,
                    db_path=db_path,
                    default_top_k=default_top_k,
                    semaphore=semaphore,
                    timeout_seconds=timeout_seconds,
                    max_retries=max_retries,
                    policy=policy,
                    budget=budget,
                    circuit_registry=circuit_registry,
                )
                for task in runnable
            ),
            return_exceptions=False,
        )
        for task_id, result, calls, warnings in batch_results:
            task_results[task_id] = result
            tool_calls.extend(calls)
            global_warnings.extend(warnings)

    observation = _observe_task_results(
        task_results,
        replan_count=replan_count,
        replan_limit=MAX_REPLAN_ROUNDS,
        tasks_by_id=by_id,
        tool_calls=tool_calls,
        budget=budget,
        context=execution_context,
    )
    observations.append(observation)

    # Bounded generalized recovery for failed read-only tasks. It reuses the
    # already successful dependency results, retries the smallest affected
    # subgraph in place, and preserves the original task ids so descendants
    # resolve their references without a business-specific rewrite.
    attempted_replans: set[str] = set()
    while replan_count < MAX_REPLAN_ROUNDS and not budget.tool_budget_exhausted:
        selected = _select_readonly_replan_candidate(
            task_results,
            by_id,
            attempted_replans,
        )
        if selected is None:
            break
        source_task_id, failed_task_id, failed_result, fingerprint = selected
        attempted_replans.add(fingerprint)
        replan_count += 1
        replan_state["replan_count"] = replan_count
        replan_state["executed_rounds"] = replan_count
        replan_state["attempted_rounds"] += 1
        affected = _task_descendants(source_task_id, by_id)
        before_dag = _dag_snapshot(by_id)
        by_id[source_task_id] = _retry_task_with_feedback(
            by_id[source_task_id],
            failed_task_id=failed_task_id,
            failed_result=failed_result,
            round_index=replan_count,
        )
        for task_id in affected:
            task_results.pop(task_id, None)

        # Do not reuse a cached failed tool result during a recovery round.
        execution_context["artifact_result_cache"] = {}
        flow_event(
            "GENERAL_READONLY_RECOVERY",
            {
                "stage": "start",
                "round": replan_count,
                "source_task_id": source_task_id,
                "failed_task_id": failed_task_id,
                "affected_tasks": sorted(affected),
                "failure_status": str(
                    _result_payload(failed_result).get("status")
                    or failed_result.get("status")
                    or ""
                ),
                "failure_errors": list(
                    failed_result.get("errors") or []
                ),
                "next_step": (
                    "reuse successful dependencies and rerun the "
                    "smallest affected read-only subgraph"
                ),
            },
            run_id=str(
                execution_context.get("run_id") or ""
            ),
            task_id=source_task_id,
            level="WARNING",
        )
        replan_audit.append(
            {
                "source": "general_readonly_recovery",
                "trigger_reason": str(
                    _result_payload(failed_result).get("next_action")
                    or failed_result.get("errors")
                    or "recoverable_readonly_failure"
                ),
                "source_task_id": source_task_id,
                "failed_task_id": failed_task_id,
                "before_dag": before_dag,
                "after_dag": _dag_snapshot(by_id),
                "reexecuted_tasks": sorted(affected),
                "blocked_tasks": [],
            }
        )
        await _execute_replan_subgraph(
            affected,
            tasks_by_id=by_id,
            task_results=task_results,
            execution_context=execution_context,
            output_dir=output_dir,
            db_path=db_path,
            default_top_k=default_top_k,
            semaphore=semaphore,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            policy=policy,
            budget=budget,
            circuit_registry=circuit_registry,
            execution_batches=execution_batches,
            tool_calls=tool_calls,
            global_warnings=global_warnings,
        )
        flow_event(
            "GENERAL_READONLY_RECOVERY",
            {
                "stage": "complete",
                "round": replan_count,
                "source_task_id": source_task_id,
                "failed_task_id": failed_task_id,
                "affected_tasks": sorted(affected),
                "task_status": {
                    task_id: {
                        "success": bool(
                            task_results.get(
                                task_id,
                                {},
                            ).get("success")
                        ),
                        "step_status": str(
                            task_results.get(
                                task_id,
                                {},
                            ).get("step_status")
                            or ""
                        ),
                        "errors": list(
                            task_results.get(
                                task_id,
                                {},
                            ).get("errors")
                            or []
                        ),
                    }
                    for task_id in sorted(affected)
                },
            },
            run_id=str(
                execution_context.get("run_id") or ""
            ),
            task_id=source_task_id,
            level=(
                "INFO"
                if all(
                    bool(
                        task_results.get(
                            task_id,
                            {},
                        ).get("success")
                    )
                    for task_id in affected
                )
                else "WARNING"
            ),
        )
        observations.append(
            _observe_task_results(
                task_results,
                replan_count=replan_count,
                replan_limit=MAX_REPLAN_ROUNDS,
                tasks_by_id=by_id,
                tool_calls=tool_calls,
                budget=budget,
                context=execution_context,
            )
        )

    terminal_before_dag = _dag_snapshot(by_id)
    changed, terminal_warnings = _apply_terminal_replan_for_empty_dependencies(task_results, by_id)
    if changed:
        global_warnings.extend(terminal_warnings)
        replan_audit.append(
            {
                "source": "deterministic_observe_terminal_skip",
                "trigger_reason": "empty_dependency_terminal_skip",
                "status": "skipped_no_replan_execution",
                "before_dag": terminal_before_dag,
                "after_dag": _dag_snapshot(by_id),
                "added_tasks": [],
                "replaced_tasks": [],
                "blocked_tasks": [],
            }
        )
        observations.append(
            {
                **_observe_task_results(
                    task_results,
                    replan_count=replan_count,
                    replan_limit=MAX_REPLAN_ROUNDS,
                    tasks_by_id=by_id,
                    tool_calls=tool_calls,
                    budget=budget,
                    context=execution_context,
                ),
                "next_action": "finish",
                "replan_reason": "empty_dependency_terminal_skip",
            }
        )

    replan_candidates: list[dict[str, Any]] = []
    if (
        replan_count < MAX_REPLAN_ROUNDS
        and replan_new_steps < MAX_REPLAN_NEW_STEPS
        and not budget.should_reduce_optional_work()
    ):
        existing_intents = {
            str(result.get("intent") or "")
            for result in task_results.values()
        }
        for source_task_id, result in list(task_results.items()):
            if "ranking" not in existing_intents and _mcp_needs_local_fallback(result):
                task = _make_mcp_local_fallback_task(
                    source_task_id,
                    result,
                    replan_new_steps + 1,
                )
                replan_candidates.append(task)
                replan_new_steps += 1
                existing_intents.add("ranking")
                if replan_new_steps >= MAX_REPLAN_NEW_STEPS:
                    break
                continue
            if "stock_news" in existing_intents:
                continue
            if not _stock_rag_needs_news_replan(result):
                continue
            task = _make_stock_news_replan_task(
                source_task_id,
                result,
                replan_new_steps + 1,
            )
            if task is not None:
                replan_candidates.append(task)
                replan_new_steps += 1
            if replan_new_steps >= MAX_REPLAN_NEW_STEPS:
                break

    if replan_candidates:
        before_dag = _dag_snapshot(by_id)
        accepted_replan, blocked_replan = _validate_replan_candidates(
            replan_candidates,
            tasks_by_id=by_id,
            budget=budget,
        )
        invalid_replan_block_count += len(blocked_replan)
        for task in accepted_replan:
            task_id = str(task.get("task_id") or "")
            if task_id:
                by_id[task_id] = task
        fallback_source_task_ids = {
            str(dep)
            for task in accepted_replan
            if str(task.get("intent") or "") == "ranking"
            for dep in (task.get("depends_on") or [])
        }
        if fallback_source_task_ids:
            for call in tool_calls:
                if str(call.get("task_id") or "") in fallback_source_task_ids and isinstance(call.get("mcp"), dict):
                    call["mcp"]["fallback_used"] = True
        replan_audit.append(
            {
                "source": "deterministic_observe",
                "trigger_reason": (
                    "mcp_evidence_use_local_ranking_fallback"
                    if any(str(task.get("intent") or "") == "ranking" for task in accepted_replan)
                    else "rag_empty_use_stock_news_fallback"
                ),
                "before_dag": before_dag,
                "after_dag": _dag_snapshot(by_id),
                "added_tasks": [str(task.get("task_id") or "") for task in accepted_replan],
                "replaced_tasks": [],
                "blocked_tasks": blocked_replan,
            }
        )
        replan_candidates = accepted_replan

    if replan_candidates:
        replan_count += 1
        replan_state["replan_count"] = replan_count
        replan_state["executed_rounds"] = replan_count
        replan_state["attempted_rounds"] += 1
        observations.append(
            {
                **_observe_task_results(
                    task_results,
                    replan_count=replan_count,
                    replan_limit=MAX_REPLAN_ROUNDS,
                    tasks_by_id=by_id,
                    tool_calls=tool_calls,
                    budget=budget,
                    context=execution_context,
                ),
                "next_action": "replan",
                "replan_reason": (
                    "mcp_evidence_use_local_ranking_fallback"
                    if any(str(task.get("intent") or "") == "ranking" for task in replan_candidates)
                    else "rag_empty_use_stock_news_fallback"
                ),
                "new_steps": [task["task_id"] for task in replan_candidates],
            }
        )
        execution_batches.append([str(task.get("task_id") or "") for task in replan_candidates])
        batch_results = await asyncio.gather(
            *(
                _execute_task_async(
                    task,
                    task_results=task_results,
                    execution_context=execution_context,
                    output_dir=output_dir,
                    db_path=db_path,
                    default_top_k=default_top_k,
                    semaphore=semaphore,
                    timeout_seconds=timeout_seconds,
                    max_retries=max_retries,
                    policy=policy,
                    budget=budget,
                    circuit_registry=circuit_registry,
                )
                for task in replan_candidates
            ),
            return_exceptions=False,
        )
        for task_id, result, calls, warnings in batch_results:
            task_results[task_id] = result
            tool_calls.extend(calls)
            global_warnings.extend(warnings)
        observations.append(
            _observe_task_results(
                task_results,
                replan_count=replan_count,
                replan_limit=MAX_REPLAN_ROUNDS,
                tasks_by_id=by_id,
                tool_calls=tool_calls,
                budget=budget,
                context=execution_context,
            )
        )

    overall_success = bool(task_results) and all(
        result.get("success", False) for result in task_results.values()
    )
    any_success = any(result.get("success", False) for result in task_results.values())
    any_failed = any(
        not result.get("success", False)
        and result.get("step_status") != AgentStepStatus.SKIPPED
        for result in task_results.values()
    )
    any_skipped = any(
        result.get("step_status") == AgentStepStatus.SKIPPED
        for result in task_results.values()
    )


    answer = ""
    if overall_success or (any_success and not any_failed):
        answer = aggregate_multi_task_answer(task_results, language=language)

    errors: list[str] = []
    for result in task_results.values():
        errors.extend(str(item) for item in (result.get("errors") or []) if str(item).strip())

    partial_success = bool(
        not overall_success
        and any_success
        and (any_skipped or any_failed)
    )
    if overall_success:
        execution_status = AgentTaskStatus.COMPLETED
        success_value = True
    elif partial_success:
        execution_status = AgentTaskStatus.PARTIALLY_COMPLETED
        success_value = True
    else:
        execution_status = AgentTaskStatus.FAILED
        success_value = False

    final_payload = {
        "success": success_value,
        "partial_success": partial_success,
        "answer": answer,
        "task_results": task_results,
        "execution_order": [str(task.get("task_id") or "") for task in ordered_tasks],
        "execution_batches": execution_batches,
        "tool_calls": tool_calls,
        "warnings": global_warnings,
        "errors": errors,
        "execution_status": execution_status,
        "observations": observations,
        "replan_count": replan_count,
        "replan_audit": replan_audit,
        "replan_state": replan_state,
        "invalid_replan_block_count": invalid_replan_block_count,
        "replan_limits": {
            "max_rounds": MAX_REPLAN_ROUNDS,
            "max_new_steps": MAX_REPLAN_NEW_STEPS,
        },
        "runtime_limits": {
            "max_concurrent_reads": max_concurrency,
            "step_timeout_seconds": timeout_seconds,
            "max_step_retries": max_retries,
            "max_tool_calls": policy.max_tool_calls,
            "max_run_steps": policy.max_run_steps,
            "max_replan_count": policy.max_replan_count,
        },
        "runtime_policy": policy.to_dict(),
        "budget_usage": budget.to_dict(),
        "circuit_states": circuit_registry.snapshot(),
        "artifact_metrics": dict(execution_context.get("artifact_metrics") or {}),
        "context_injected": {
            "user_id": user_id,
            "session_id_present": bool(session_id),
            "default_top_k": default_top_k,
        },
    }
    trace_event(
        "dag.plan.complete",
        {
            "success": final_payload.get("success"),
            "execution_status": final_payload.get("execution_status"),
            "task_results": final_payload.get("task_results"),
            "warnings": final_payload.get("warnings"),
            "errors": final_payload.get("errors"),
            "observations": final_payload.get("observations"),
            "replan_audit": final_payload.get("replan_audit"),
        },
        run_id=str(execution_context.get("run_id") or ""),
    )
    return final_payload


def execute_multi_intent_plan(
    decomposition: dict[str, Any],
    *,
    user_id: str,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    default_top_k: int = 10,
    session_id: str = "",
    language: str = "zh",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _run_coroutine_blocking(
        execute_multi_intent_plan_async(
            decomposition,
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
            default_top_k=default_top_k,
            session_id=session_id,
            language=language,
            context=context,
        )
    )
