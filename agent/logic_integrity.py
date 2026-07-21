"""Deterministic integrity checks for Agent execution state.

The Agent may use an LLM to interpret a request, but a model must never decide
that contradictory portfolio data, missing required evidence or an unsafe
write path is acceptable.  This module is deliberately dependency-free so it
also protects no-LLM and degraded-mode runs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


FEATURE_UNAVAILABLE_MESSAGE_ZH = "当前功能出现异常，暂时无法可靠完成该请求，请等待后续版本更新完善。本次未执行任何写操作。"
FEATURE_UNAVAILABLE_MESSAGE_EN = (
    "The current feature encountered an error and cannot reliably complete this request. "
    "Please wait for a future version update. No write operations were performed in this request."
)


@dataclass(frozen=True)
class LogicIntegrityResult:
    status: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    safe_to_continue: bool = True
    safe_to_answer: bool = True
    safe_to_write: bool = True
    recommended_action: str = "continue"
    error_code: str = ""

    @property
    def is_logic_error(self) -> bool:
        return self.status == "logic_error"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_terminal_agent_state(value: Any) -> bool:
    """Return whether an execution fact must suppress model-led recovery."""

    if isinstance(value, LogicIntegrityResult):
        return value.is_logic_error
    if isinstance(value, dict):
        return str(value.get("status") or "").lower() in {
            "logic_error",
            "feature_unavailable",
        } or value.get("safe_to_continue") is False
    return str(value or "").lower() in {"logic_error", "feature_unavailable"}


def terminal_completion_payload(integrity: LogicIntegrityResult) -> dict[str, Any]:
    """Deterministic Completion result used before any Completion LLM call."""

    return {
        "status": "invalid",
        "completion_status": "report_limitation",
        "next_action": "report_limitation",
        "missing_outputs": [],
        "reason": "terminal_logic_integrity",
        "logic_integrity": integrity.to_dict(),
        "safe_to_continue": False,
        "safe_to_write": False,
    }


def terminal_critic_payload(integrity: LogicIntegrityResult, *, requested_action: str = "") -> dict[str, Any]:
    """Deterministic Critic result; it can document but never execute Replan."""

    return {
        "action": "BLOCK_AND_REPORT",
        "status": "terminal_logic_integrity",
        "suppressed_action": str(requested_action or "REPLAN_READONLY"),
        "suppressed_reason": "terminal_priority_logic_error",
        "logic_integrity": integrity.to_dict(),
        "safe_to_continue": False,
        "safe_to_write": False,
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _task_results(value: Any) -> dict[str, dict[str, Any]]:
    rows = _mapping(value)
    return {str(key): _mapping(item) for key, item in rows.items() if isinstance(item, dict)}


def _required_outputs(value: Any) -> set[str]:
    if isinstance(value, dict):
        items = value.get("required_outputs") or value.get("expected_outputs") or []
    else:
        items = value or []
    return {str(item).strip() for item in items if str(item).strip()}


def _produced_outputs(results: dict[str, dict[str, Any]]) -> set[str]:
    produced: set[str] = set()
    for result in results.values():
        data = _mapping(result.get("data"))
        produced.update(str(key) for key, value in data.items() if value not in (None, "", [], {}))
        explicit = result.get("produced_outputs") or data.get("produced_outputs") or []
        if isinstance(explicit, dict):
            produced.update(str(key) for key, value in explicit.items() if value not in (None, "", [], {}))
        else:
            produced.update(str(item) for item in explicit if str(item).strip())
    return produced


def _snapshot_error_codes(portfolio_state: dict[str, Any], risk_report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    snapshot = _mapping(portfolio_state.get("portfolio_snapshot"))
    states = [portfolio_state, snapshot, risk_report]
    for state in states:
        status = str(state.get("consistency_status") or state.get("status") or "").lower()
        if status in {"rejected", "logic_error", "invalid_portfolio_snapshot"}:
            errors.append("portfolio_snapshot_inconsistent")
        if state.get("safe_to_continue") is False:
            errors.append("portfolio_snapshot_inconsistent")
    state_id = str(portfolio_state.get("snapshot_id") or snapshot.get("snapshot_id") or "")
    risk_id = str(risk_report.get("snapshot_id") or "")
    if state_id and risk_id and state_id != risk_id:
        errors.append("portfolio_snapshot_id_mismatch")
    return errors


def validate_agent_logic_integrity(
    *,
    portfolio_state: dict[str, Any] | None = None,
    risk_report: dict[str, Any] | None = None,
    task_plan: dict[str, Any] | None = None,
    task_results: dict[str, Any] | None = None,
    completion: dict[str, Any] | None = None,
    replan_audit: list[dict[str, Any]] | None = None,
    replan_count: int | None = None,
    replan_limit: int | None = None,
    required_outputs: list[str] | None = None,
    required_artifacts: list[str] | None = None,
    enforce_task_count: bool = True,
    write_requested: bool = False,
    write_allowed: bool = True,
) -> LogicIntegrityResult:
    """Validate execution facts without calling an LLM.

    ``logic_error`` is terminal for recommendations, Replan and writes.  A
    warning has no permission effect and records a non-contradictory condition
    such as a requested but not-yet-run replan.
    """

    portfolio = _mapping(portfolio_state)
    risk = _mapping(risk_report)
    plan = _mapping(task_plan)
    results = _task_results(task_results)
    complete = _mapping(completion)
    audit = [dict(item) for item in (replan_audit or []) if isinstance(item, dict)]
    errors = _snapshot_error_codes(portfolio, risk)
    warnings: list[str] = []

    planned_tasks = [item for item in (plan.get("tasks") or []) if isinstance(item, dict)]
    if enforce_task_count and planned_tasks and results:
        planned_ids = {str(item.get("task_id") or "") for item in planned_tasks if item.get("task_id")}
        executed_ids = set(results)
        if planned_ids and not planned_ids.issubset(executed_ids):
            errors.append("task_plan_result_count_mismatch")

    # Planner-internal ``expected_outputs`` often describe optional display
    # fragments (for example help text), not a completion contract.  Only an
    # explicit caller contract or Completion's required outputs can make a
    # missing artifact terminal.
    expected = _required_outputs(required_outputs) or _required_outputs(complete)
    if expected and results:
        missing = expected - _produced_outputs(results)
        if missing:
            errors.append("required_output_missing:" + ",".join(sorted(missing)))

    artifacts = {str(item).strip() for item in (required_artifacts or []) if str(item).strip()}
    if artifacts:
        produced = _produced_outputs(results)
        empty = artifacts - produced
        if empty:
            errors.append("required_artifact_empty:" + ",".join(sorted(empty)))

    completion_status = str(complete.get("status") or "").lower()
    if completion_status in {"completed", "complete", "success"} and any(not bool(item.get("success")) for item in results.values()):
        errors.append("completion_false_success")

    # A target design that cannot be validated against a mandatory safety
    # constraint is terminal.  It must not be rewritten into a generic
    # recommendation by Completion, Critic or the final report layer.
    for result in results.values():
        data = _mapping(result.get("data"))
        feedback = _mapping(data.get("validation_feedback"))
        feedback_errors = [item for item in (feedback.get("errors") or []) if isinstance(item, dict)]
        nonrepairable_codes = {
            str(item.get("code") or "")
            for item in feedback_errors
            if item.get("repairable_by_llm") is False
        }
        if (
            str(result.get("status") or data.get("status") or "").lower() == "invalid_llm_target_design"
            and data.get("repairable") is False
        ) or "industry_constraint_unverifiable" in nonrepairable_codes:
            errors.append("target_design_constraint_unreliable")

    wants_replan = str(complete.get("next_action") or "").lower() in {"replan", "replan_readonly"}
    executed_rounds = [
        item
        for item in audit
        if str(item.get("status") or "") in {"executed", "no_progress"}
        and bool(item.get("executed_tasks") or item.get("execution_status") is not None)
    ]
    if replan_count is not None and int(replan_count) != len(executed_rounds):
        errors.append("replan_count_execution_mismatch")
    if wants_replan and not executed_rounds and audit and all(str(item.get("status") or "") == "blocked" for item in audit):
        errors.append("replan_required_but_not_executed")
    if wants_replan and not audit:
        warnings.append("replan_requested_pending_execution")
    if replan_limit is not None and int(replan_count or 0) > int(replan_limit):
        errors.append("replan_limit_exceeded")
    if any(str(item.get("status") or "") in {"no_progress", "bounded_replan_exhausted"} for item in audit):
        errors.append("replan_no_reliable_progress")

    if write_requested and not write_allowed:
        errors.append("write_plan_blocked_by_logic_integrity")

    deduped_errors = list(dict.fromkeys(errors))
    deduped_warnings = list(dict.fromkeys(warnings))
    if deduped_errors:
        return LogicIntegrityResult(
            status="logic_error",
            errors=deduped_errors,
            warnings=deduped_warnings,
            safe_to_continue=False,
            safe_to_answer=False,
            safe_to_write=False,
            recommended_action="feature_unavailable",
            error_code=deduped_errors[0].split(":", 1)[0],
        )
    if deduped_warnings:
        return LogicIntegrityResult(
            status="warning",
            warnings=deduped_warnings,
            safe_to_continue=True,
            safe_to_answer=True,
            safe_to_write=not write_requested or write_allowed,
            recommended_action="continue_readonly",
        )
    return LogicIntegrityResult(status="ok")


def feature_unavailable_payload(
    integrity: LogicIntegrityResult,
    *,
    language: str = "zh",
) -> dict[str, Any]:
    """Return the deterministic, non-overridable safe user-facing payload."""

    english = str(language or "").lower().startswith("en")
    return {
        "success": False,
        "status": "feature_unavailable",
        "error_code": integrity.error_code or "agent_logic_error",
        "message": FEATURE_UNAVAILABLE_MESSAGE_EN if english else FEATURE_UNAVAILABLE_MESSAGE_ZH,
        "user_visible": True,
        "safe_to_continue": False,
        "safe_to_answer": True,
        "safe_to_write": False,
        "retryable": False,
        "requires_version_update": True,
        "logic_integrity": integrity.to_dict(),
        "no_write_performed": True,
    }
