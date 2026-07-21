from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Callable

from agent.tool_engine import OP_READ, get_tool_registry_v2


CANONICAL_REPLAN_READONLY = "replan_readonly"
DEFAULT_REPLAN_LIMIT = 2
_READONLY_ACTIONS = {
    "replan",
    "replan_readonly",
    "replan_target_design",
    "retry_readonly",
}
_PROHIBITED_INTENTS = {
    "confirm_execute",
    "one_time_position_operation",
    "adjust_position",
    "preview_add_stock",
    "capital_management",
    "backfill",
    "strategy_change",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def ensure_replan_state(
    state: dict[str, Any] | None = None,
    *,
    replan_count: int = 0,
    replan_limit: int | None = None,
    replan_audit: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the sole mutable Replan state used by every recovery route.

    ``replan_count`` records only recovery rounds that actually started
    execution.  Rejected, duplicate, terminal and unsafe requests are kept in
    ``attempted_rounds`` and the audit, without consuming the bounded budget.
    """

    current = dict(state or {})
    limit = max(0, int(current.get("replan_limit", replan_limit if replan_limit is not None else DEFAULT_REPLAN_LIMIT)))
    audit = [dict(item) for item in (current.get("replan_audit") or replan_audit or []) if isinstance(item, dict)]
    executed = max(0, int(current.get("executed_rounds", current.get("replan_count", replan_count)) or 0))
    attempted = max(0, int(current.get("attempted_rounds", 0) or 0))
    return {
        **current,
        "replan_count": executed,
        "replan_limit": limit,
        "executed_rounds": executed,
        "attempted_rounds": attempted,
        "replan_audit": audit,
    }


def request_replan(
    state: dict[str, Any],
    *,
    source: str,
    action: Any,
    missing_outputs: list[str] | None = None,
    source_task_id: str = "",
    failed_task_ids: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Record a request before deciding whether it can be executed.

    This function deliberately has no access to tools; callers must use
    :func:`execute_replan` immediately before an actual recovery execution.
    """

    current = ensure_replan_state(state)
    canonical = canonical_replan_action(action)
    entry = _base_audit_entry(
        source=source,
        action=canonical or str(action or "").lower(),
        replan_count=current["replan_count"],
        replan_limit=current["replan_limit"],
        missing_outputs=sorted({str(item) for item in (missing_outputs or []) if str(item).strip()}),
    )
    entry.update(
        {
            "trigger_sources": [source],
            "source_task_id": str(source_task_id or ""),
            "failed_task_ids": sorted({str(item) for item in (failed_task_ids or []) if str(item)}),
            "requested_at": _utc_now(),
            "attempted": bool(canonical),
            "executed": False,
        }
    )
    if canonical:
        current["attempted_rounds"] += 1
    return current, entry


def execute_replan(state: dict[str, Any], entry: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Claim one bounded recovery round immediately before tool execution."""

    current = ensure_replan_state(state)
    if not entry.get("attempted"):
        return current, False
    if current["replan_count"] >= current["replan_limit"]:
        return current, False
    current["replan_count"] += 1
    current["executed_rounds"] = current["replan_count"]
    entry.update(
        {
            "round": current["replan_count"],
            "replan_count": current["replan_count"],
            "status": "executing",
            "executed": True,
            "execution_started_at": _utc_now(),
        }
    )
    return current, True


def record_replan_result(
    state: dict[str, Any],
    entry: dict[str, Any],
    *,
    status: str,
    stop_reason: str = "",
) -> dict[str, Any]:
    """Finalize a Replan audit item and publish its authoritative state."""

    current = ensure_replan_state(state)
    entry.update(
        {
            "status": str(status or entry.get("status") or "not_executed"),
            "stop_reason": str(stop_reason or entry.get("stop_reason") or ""),
            "finished_at": _utc_now(),
        }
    )
    current["replan_audit"] = [*list(current.get("replan_audit") or []), entry]
    return current


def canonical_replan_action(value: Any) -> str:
    """Normalize Completion strings and Critic enum values to one internal action."""

    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    return CANONICAL_REPLAN_READONLY if text in _READONLY_ACTIONS else ""


def _result_data(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data") if isinstance(result, dict) else {}
    return dict(data) if isinstance(data, dict) else {}


def _first_result_data(task_results: dict[str, dict[str, Any]], intents: set[str]) -> tuple[str, dict[str, Any]]:
    for task_id, result in task_results.items():
        if str(result.get("intent") or "") in intents and result.get("success"):
            return str(task_id), _result_data(result)
    return "", {}


def _target_portfolio_tasks(
    *,
    round_index: int,
    task_results: dict[str, dict[str, Any]],
    user_goal: dict[str, Any],
) -> list[dict[str, Any]]:
    state_id, current_portfolio = _first_result_data(task_results, {"portfolio_state", "portfolio.get_state"})
    ranking_id, ranking = _first_result_data(task_results, {"ranking", "market.get_ranking"})
    _, risk = _first_result_data(task_results, {"portfolio_risk", "portfolio.analyze_risk"})
    if not state_id or not ranking_id:
        return []
    design_id = f"replan_{round_index}_target_design"
    construct_id = f"replan_{round_index}_target_portfolio"
    return [
        {
            "task_id": design_id,
            "intent": "portfolio.design_target_portfolio",
            "parameters": {
                "current_portfolio": current_portfolio,
                "ranking": ranking,
                "risk_report": risk.get("risk_report") or risk.get("risk") or risk,
                "query": str(user_goal.get("raw_message") or ""),
                "user_goal": dict(user_goal or {}),
            },
            "depends_on": [],
            "reason": "bounded readonly replan for missing target_portfolio",
            "capability_status": "executable",
        },
        {
            "task_id": construct_id,
            "intent": "portfolio.construct_target_portfolio",
            "parameters": {
                "current_portfolio": current_portfolio,
                "ranking": ranking,
                "risk_report": risk.get("risk_report") or risk.get("risk") or risk,
                "target_design_source": f"${design_id}.target_design",
            },
            "depends_on": [design_id],
            "reason": "materialize readonly target portfolio from replan design",
            "capability_status": "executable",
        },
    ]


def build_readonly_replan_tasks(
    *,
    round_index: int,
    missing_outputs: list[str] | None,
    task_results: dict[str, dict[str, Any]],
    user_goal: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Create the smallest safe plan for Completion/Critic gaps.

    No task is inferred from free text: target construction has an explicit
    structured recipe, while all other recovery steps can only refresh an
    already executed read-only task whose registry contract produces the gap.
    """

    expected = {str(item) for item in (missing_outputs or []) if str(item).strip()}
    if "target_portfolio" in expected:
        tasks = _target_portfolio_tasks(
            round_index=round_index,
            task_results=task_results,
            user_goal=dict(user_goal or {}),
        )
        if tasks:
            return tasks

    registry = get_tool_registry_v2()
    for task_id, result in task_results.items():
        intent = str(result.get("intent") or "")
        definition = registry.get(intent)
        if definition is None or definition.operation_type != OP_READ:
            continue
        produced = {str(item) for item in (definition.produced_outputs or [])}
        if expected and not (produced & expected):
            continue
        arguments = dict(result.get("arguments") or {})
        return [
            {
                "task_id": f"replan_{round_index}_refresh_{task_id}",
                "intent": intent,
                "parameters": arguments,
                "depends_on": [],
                "reason": "bounded readonly refresh for incomplete completion contract",
                "capability_status": "executable",
            }
        ]
    return []


def validate_readonly_replan_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, str]]:
    registry = get_tool_registry_v2()
    blocked: list[dict[str, str]] = []
    for task in tasks:
        task_id = str(task.get("task_id") or "")
        intent = str(task.get("intent") or "")
        definition = registry.get(intent)
        reason = ""
        if not task_id or not intent:
            reason = "invalid_replan_task"
        elif intent in _PROHIBITED_INTENTS:
            reason = "write_task_not_allowed_in_replan"
        elif definition is None:
            reason = "unknown_replan_tool"
        elif definition.operation_type != OP_READ:
            reason = "non_readonly_tool_not_allowed_in_replan"
        elif any(key in dict(task.get("parameters") or {}) for key in ("confirmation_token", "plan_id", "proposal_id")):
            reason = "mutation_parameter_not_allowed_in_replan"
        if reason:
            blocked.append({"task_id": task_id, "intent": intent, "reason": reason})
    return blocked


_SECRET_OR_VOLATILE_FIELDS = {
    "confirmation_token",
    "api_key",
    "token",
    "password",
    "secret",
    "created_at",
    "updated_at",
    "timestamp",
    "executed_at",
    "run_id",
}


def _normalized_for_signature(value: Any, *, drop_task_id: bool = False) -> Any:
    """Create a reproducible signature input without secrets or timestamps."""

    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in _SECRET_OR_VOLATILE_FIELDS:
                continue
            if drop_task_id and key_text in {"task_id", "reason", "round", "replan_count"}:
                continue
            normalized[key_text] = _normalized_for_signature(item, drop_task_id=drop_task_id)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalized_for_signature(item, drop_task_id=drop_task_id) for item in value]
    if isinstance(value, str):
        return re.sub(r"replan_\d+_", "replan_*_", value)
    return value


def _signature(value: Any, *, drop_task_id: bool = False) -> str:
    canonical = json.dumps(
        _normalized_for_signature(value, drop_task_id=drop_task_id),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _output_summary(task_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for task_id, result in task_results.items():
        if not bool(result.get("success")):
            continue
        data = _result_data(result)
        for key, value in data.items():
            if value not in (None, "", [], {}):
                # Artifact identity is semantic rather than the generated
                # replan task id.  Otherwise round-2's identical output would
                # falsely look new solely because its task id changed.
                summary[str(key)] = value
        explicit = result.get("produced_outputs") or data.get("produced_outputs") or []
        if isinstance(explicit, dict):
            for key, value in explicit.items():
                if value not in (None, "", [], {}):
                    summary[str(key)] = value
        else:
            for key in explicit:
                if str(key).strip():
                    summary[str(key)] = True
    return summary


def _missing_after_execution(missing_before: list[str], produced_after: dict[str, Any]) -> list[str]:
    keys = set(produced_after)
    short_keys = {item.rsplit(":", 1)[-1] for item in keys}
    return [item for item in missing_before if item not in keys and item not in short_keys]


def _base_audit_entry(
    *,
    source: str,
    action: str,
    replan_count: int,
    replan_limit: int,
    missing_outputs: list[str],
) -> dict[str, Any]:
    return {
        "round": None,
        "source": source,
        "trigger_source": source,
        "trigger_sources": [source],
        "action": action,
        "replan_count": replan_count,
        "replan_limit": replan_limit,
        "executed_rounds": replan_count,
        "attempted_rounds": 0,
        "missing_outputs": list(missing_outputs),
        "missing_outputs_before": list(missing_outputs),
        "missing_outputs_after": list(missing_outputs),
        "planned_tasks": [],
        "planned_tool_calls": [],
        "executed_tasks": [],
        "produced_outputs_before": {},
        "produced_outputs_after": {},
        "new_or_changed_outputs": {},
        "progress_status": "not_started",
        "stop_reason": "",
        "request_signature": "",
        "plan_signature": "",
        "result_signature": "",
        "attempted": True,
        "executed": False,
        "requested_at": _utc_now(),
        "execution_started_at": "",
        "finished_at": "",
    }


def consume_readonly_replan(
    *,
    source: str,
    action: Any,
    replan_count: int,
    replan_limit: int | None,
    replan_audit: list[dict[str, Any]] | None,
    task_results: dict[str, dict[str, Any]],
    missing_outputs: list[str] | None = None,
    user_goal: dict[str, Any] | None = None,
    execute_plan: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None,
    safe_to_continue: bool = True,
    safe_to_write: bool = True,
    goal_completed: bool = False,
    budget_exhausted: bool = False,
) -> dict[str, Any]:
    """Consume exactly one canonical read-only Replan request.

    The counter is incremented immediately before a safe plan is executed, so
    it represents real attempts and cannot grow for mere log messages.
    """

    state = ensure_replan_state(
        replan_count=replan_count,
        replan_limit=replan_limit,
        replan_audit=replan_audit,
    )
    canonical = canonical_replan_action(action)
    audit = state["replan_audit"]
    limit = state["replan_limit"]
    if not canonical:
        return {"consumed": False, "replan_count": state["replan_count"], "replan_audit": audit, "replan_state": state, "status": "not_requested"}
    missing_before = sorted({str(item) for item in (missing_outputs or []) if str(item).strip()})
    state["attempted_rounds"] += 1
    count = state["replan_count"]

    def _append(entry: dict[str, Any]) -> None:
        entry["attempted_rounds"] = state["attempted_rounds"]
        entry["executed_rounds"] = state["executed_rounds"]
        entry["finished_at"] = _utc_now()
        audit.append(entry)

    if not safe_to_continue or not safe_to_write:
        entry = _base_audit_entry(
            source=source,
            action=canonical,
            replan_count=count,
            replan_limit=limit,
            missing_outputs=missing_before,
        )
        entry.update({"status": "logic_error", "progress_status": "stopped", "stop_reason": "logic_error"})
        _append(entry)
        return {"consumed": True, "replan_count": count, "replan_audit": audit, "replan_state": state, "status": "logic_error", "execution": {}}
    if goal_completed:
        entry = _base_audit_entry(source=source, action=canonical, replan_count=count, replan_limit=limit, missing_outputs=missing_before)
        entry.update({"status": "goal_completed", "progress_status": "stopped", "stop_reason": "goal_completed"})
        _append(entry)
        return {"consumed": True, "replan_count": count, "replan_audit": audit, "replan_state": state, "status": "goal_completed", "execution": {}}
    if budget_exhausted:
        entry = _base_audit_entry(source=source, action=canonical, replan_count=count, replan_limit=limit, missing_outputs=missing_before)
        entry.update({"status": "budget_exhausted", "progress_status": "stopped", "stop_reason": "budget_exhausted"})
        _append(entry)
        return {"consumed": True, "replan_count": count, "replan_audit": audit, "replan_state": state, "status": "budget_exhausted", "execution": {}}
    if count >= limit:
        entry = _base_audit_entry(source=source, action=canonical, replan_count=count, replan_limit=limit, missing_outputs=missing_before)
        entry.update({"status": "bounded_replan_exhausted", "progress_status": "stopped", "stop_reason": "replan_limit_reached"})
        _append(entry)
        return {"consumed": True, "replan_count": count, "replan_audit": audit, "replan_state": state, "status": "bounded_replan_exhausted", "execution": {}}

    round_index = count + 1
    tasks = build_readonly_replan_tasks(
        round_index=round_index,
        missing_outputs=missing_before,
        task_results=task_results,
        user_goal=user_goal,
    )
    blocked = validate_readonly_replan_tasks(tasks)
    if not tasks or blocked:
        entry = _base_audit_entry(source=source, action=canonical, replan_count=count, replan_limit=limit, missing_outputs=missing_before)
        entry.update(
            {
                "status": "blocked",
                "progress_status": "stopped",
                "stop_reason": "write_plan_blocked" if blocked else "no_safe_replan_task",
                "planned_tasks": tasks,
                "blocked_tasks": blocked or [{"reason": "no_safe_replan_task"}],
            }
        )
        _append(entry)
        return {"consumed": True, "replan_count": count, "replan_audit": audit, "replan_state": state, "status": "blocked", "execution": {}}

    plan_signature = _signature(tasks, drop_task_id=True)
    request_signature = _signature({"goal": user_goal or {}, "missing_outputs": missing_before}, drop_task_id=True)
    for previous in reversed(audit):
        if previous.get("request_signature") == request_signature and previous.get("status") == "executed":
            entry = _base_audit_entry(source=source, action=canonical, replan_count=count, replan_limit=limit, missing_outputs=missing_before)
            entry.update(
                {
                    "status": "deduplicated",
                    "progress_status": "stopped",
                    "stop_reason": "same_request_already_executed",
                    "request_signature": request_signature,
                    "plan_signature": plan_signature,
                    "deduplicated_with_round": previous.get("round"),
                }
            )
            _append(entry)
            return {"consumed": True, "replan_count": count, "replan_audit": audit, "replan_state": state, "status": "deduplicated", "execution": {}}
        if previous.get("plan_signature") == plan_signature and previous.get("progress_status") in {"no_progress", "stopped"}:
            entry = _base_audit_entry(source=source, action=canonical, replan_count=count, replan_limit=limit, missing_outputs=missing_before)
            entry.update(
                {
                    "status": "no_progress",
                    "progress_status": "stopped",
                    "stop_reason": "same_plan_without_progress",
                    "request_signature": request_signature,
                    "plan_signature": plan_signature,
                }
            )
            _append(entry)
            return {"consumed": True, "replan_count": count, "replan_audit": audit, "replan_state": state, "status": "no_progress", "execution": {}}

    produced_before = _output_summary(task_results)
    unresolved_before = _missing_after_execution(missing_before, produced_before)
    audit_entry = _base_audit_entry(source=source, action=canonical, replan_count=round_index, replan_limit=limit, missing_outputs=unresolved_before)
    audit_entry.update({
        "status": "executing",
        "round": round_index,
        "request_signature": request_signature,
        "plan_signature": plan_signature,
        "planned_tasks": [{"task_id": item["task_id"], "intent": item["intent"], "parameters": dict(item.get("parameters") or {})} for item in tasks],
        "planned_tool_calls": [{"intent": item["intent"], "parameters": dict(item.get("parameters") or {})} for item in tasks],
        "blocked_tasks": [],
        "produced_outputs_before": produced_before,
    })
    state, allowed_to_execute = execute_replan(state, audit_entry)
    if not allowed_to_execute:
        audit_entry.update({"status": "bounded_replan_exhausted", "progress_status": "stopped", "stop_reason": "replan_limit_reached"})
        _append(audit_entry)
        return {"consumed": True, "replan_count": state["replan_count"], "replan_audit": audit, "replan_state": state, "status": "bounded_replan_exhausted", "execution": {}}
    audit_entry["attempted_rounds"] = state["attempted_rounds"]
    audit_entry["executed_rounds"] = state["executed_rounds"]
    audit.append(audit_entry)
    execution = execute_plan(tasks) if execute_plan is not None else {}
    audit_entry["status"] = "executed"
    audit_entry["execution_status"] = str(execution.get("execution_status") or "")
    audit_entry["executed_tasks"] = list((execution.get("task_results") or {}).keys())
    execution_results = {
        str(task_id): dict(result)
        for task_id, result in dict(execution.get("task_results") or {}).items()
        if isinstance(result, dict)
    }
    produced_after = {**produced_before, **_output_summary(execution_results)}
    missing_after = _missing_after_execution(unresolved_before, produced_after)
    new_or_changed = {
        key: value
        for key, value in produced_after.items()
        if key not in produced_before or produced_before[key] != value
    }
    result_signature = _signature(list(execution_results.values()), drop_task_id=True)
    audit_entry["result_signature"] = result_signature
    audit_entry["produced_outputs_after"] = produced_after
    audit_entry["new_or_changed_outputs"] = new_or_changed
    audit_entry["missing_outputs_after"] = missing_after
    previous_results = [item.get("result_signature") for item in audit[:-1] if item.get("result_signature")]
    made_progress = len(missing_after) < len(unresolved_before) or bool(new_or_changed)
    if result_signature in previous_results and not made_progress:
        audit_entry.update({"progress_status": "no_progress", "stop_reason": "same_result_without_progress", "status": "no_progress"})
        status = "no_progress"
    elif not made_progress:
        audit_entry.update({"progress_status": "no_progress", "stop_reason": "no_new_valid_evidence", "status": "no_progress"})
        status = "no_progress"
    else:
        audit_entry["progress_status"] = "progress"
        status = "executed"
    audit_entry["finished_at"] = _utc_now()
    return {"consumed": True, "replan_count": state["replan_count"], "replan_audit": audit, "replan_state": state, "status": status, "execution": execution}
