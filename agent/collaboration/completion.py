"""Capability-contract completion reports and deterministic flow decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import GraphAgentTask, ResultStatus
from .worker_contracts import WorkerContractViolation

COMPLETION_CONTRACT_VERSION = "capability-contract-list.v1"
COMPLETION_REPORT_VERSION = "capability-contract-report.v1"


@dataclass(frozen=True)
class CompletionFlowDecision:
    result_status: ResultStatus
    semantic_satisfied: bool
    should_freeze: bool
    reusable: bool
    replan_recommended: bool
    failure_kind: str
    freeze_reason: str


def _contracts(task_or_contract: GraphAgentTask | dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(task_or_contract, dict):
        rows = task_or_contract.get("contracts") or []
    else:
        rows = task_or_contract.contracts
    return [dict(item) for item in rows if isinstance(item, dict)]


def _output_slots(task_or_contract: GraphAgentTask | dict[str, Any]) -> list[str]:
    result: list[str] = []
    for contract in _contracts(task_or_contract):
        for row in contract.get("promised_outputs") or []:
            if not isinstance(row, dict):
                continue
            slot = str(row.get("slot_id") or "").strip()
            if slot and slot not in result:
                result.append(slot)
    return result


def compile_completion_contract(task: GraphAgentTask) -> dict[str, Any]:
    """Return the canonical capability contract carried by the task."""
    return {
        "schema_version": COMPLETION_CONTRACT_VERSION,
        "contracts": [dict(item) for item in task.contracts],
        "required_information_slots": _output_slots(task),
        "output_type": "CapabilityResult",
    }


def _rule_rows(task_or_contract: GraphAgentTask | dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for contract in _contracts(task_or_contract):
        contract_id = str(contract.get("contract_id") or "")
        for rule_id in contract.get("acceptance_rule_ids") or []:
            rows.append({
                "contract_id": contract_id,
                "rule_id": str(rule_id),
                "satisfied": True,
                "reason": "",
                "evidence_paths": [],
            })
    return rows


def validate_completion_report(
    report: dict[str, Any],
    contract: dict[str, Any] | GraphAgentTask,
    *,
    path: str = "$.completion",
) -> None:
    if not isinstance(report, dict):
        raise WorkerContractViolation("completion_report_not_object", path, type(report).__name__)
    if str(report.get("schema_version") or "") != COMPLETION_REPORT_VERSION:
        raise WorkerContractViolation(
            "completion_report_version_mismatch", f"{path}.schema_version",
            str(report.get("schema_version") or ""),
        )
    expected = set(_output_slots(contract))
    produced = {str(item) for item in report.get("produced_information_slots") or [] if str(item)}
    missing = {str(item) for item in report.get("missing_information_slots") or [] if str(item)}
    if produced & missing:
        raise WorkerContractViolation("completion_report_slot_overlap", path, ",".join(sorted(produced & missing)))
    unknown = (produced | missing) - expected
    if expected and unknown:
        raise WorkerContractViolation("completion_report_unknown_information_slot", path, ",".join(sorted(unknown)))
    if expected and produced | missing != expected:
        absent = expected - produced - missing
        raise WorkerContractViolation("completion_report_slot_partition_incomplete", path, ",".join(sorted(absent)))
    completed = bool(report.get("expected_task_completed"))
    if completed and missing:
        raise WorkerContractViolation("completed_report_cannot_have_missing_slots", path, ",".join(sorted(missing)))


def build_completion_report(
    task: GraphAgentTask,
    *,
    execution_status: str,
    contract_status: str,
    business_status: str,
    completion_status: str,
    expected_task_completed: bool,
    produced_information_slots: list[str],
    criterion_results: list[dict[str, Any]] | None = None,
    limitations: list[str] | None = None,
    failure_kind: str = "none",
    report_source: str = "runtime",
) -> dict[str, Any]:
    expected = _output_slots(task)
    produced = list(dict.fromkeys(str(item) for item in produced_information_slots if str(item)))
    missing = [slot for slot in expected if slot not in set(produced)]
    report = {
        "schema_version": COMPLETION_REPORT_VERSION,
        "report_source": str(report_source or "runtime"),
        "execution_status": str(execution_status),
        "contract_status": str(contract_status),
        "business_status": str(business_status),
        "completion_status": str(completion_status),
        "expected_task_completed": bool(expected_task_completed),
        "output_type": "CapabilityResult",
        "produced_information_slots": produced,
        "missing_information_slots": missing,
        "criteria": [dict(item) for item in (criterion_results or _rule_rows(task))],
        "limitations": [str(item) for item in limitations or [] if str(item).strip()],
        "failure_kind": str(failure_kind or "none"),
        "contract_reports": [],
    }
    validate_completion_report(report, task)
    return report


def non_success_completion_report(
    task: GraphAgentTask,
    *,
    execution_status: str,
    reason: str,
    failure_kind: str,
) -> dict[str, Any]:
    expected = _output_slots(task)
    return {
        "schema_version": COMPLETION_REPORT_VERSION,
        "report_source": "runtime",
        "execution_status": str(execution_status),
        "contract_status": "not_satisfied",
        "business_status": "unknown",
        "completion_status": "not_completed",
        "expected_task_completed": False,
        "output_type": "CapabilityResult",
        "produced_information_slots": [],
        "missing_information_slots": expected,
        "criteria": [
            {**row, "satisfied": False, "reason": str(reason)[:1000]}
            for row in _rule_rows(task)
        ],
        "limitations": [str(reason)[:1000]],
        "failure_kind": str(failure_kind),
        "contract_reports": [],
    }


def runtime_completion_report(
    task: GraphAgentTask,
    *,
    result_status: ResultStatus,
    output_type: str,
    data: dict[str, Any] | None,
    error: dict[str, Any] | None,
) -> dict[str, Any]:
    del output_type
    success = result_status in {ResultStatus.COMPLETED, ResultStatus.PROPOSAL_READY}
    produced: list[str] = []
    if isinstance(data, dict) and isinstance(data.get("slots"), dict):
        produced = [
            str(slot_id)
            for slot_id, value in data["slots"].items()
            if str(slot_id) and value is not None
        ]
    business_empty = bool(isinstance(data, dict) and (data.get("business_empty") is True or data.get("found") is False))
    return build_completion_report(
        task,
        execution_status=result_status.value,
        contract_status="satisfied" if success else "not_satisfied",
        business_status="empty" if business_empty else "available" if success else "unknown",
        completion_status="completed" if success else "not_completed",
        expected_task_completed=success,
        produced_information_slots=produced,
        limitations=[] if success else [str((error or {}).get("message") or "Worker did not complete.")],
        failure_kind="none" if success else str((error or {}).get("code") or "worker_execution_failure"),
    )


def flow_decision(
    result_status: ResultStatus,
    completion: dict[str, Any],
    *,
    output_type: str = "",
    retryable: bool = False,
) -> CompletionFlowDecision:
    del output_type
    completed = bool(completion.get("expected_task_completed"))
    failure_kind = str(completion.get("failure_kind") or "none")
    if completed:
        status = ResultStatus.PROPOSAL_READY if result_status == ResultStatus.PROPOSAL_READY else ResultStatus.COMPLETED
        return CompletionFlowDecision(status, True, True, True, False, "none", "required_contracts_satisfied")
    if result_status == ResultStatus.NEED_CONTEXT:
        return CompletionFlowDecision(ResultStatus.NEED_CONTEXT, False, False, False, True, failure_kind or "context_missing", "context_required")
    if result_status == ResultStatus.BLOCKED:
        return CompletionFlowDecision(
            ResultStatus.BLOCKED, False, False, False, bool(retryable),
            failure_kind or "blocked", "blocked",
        )
    if result_status == ResultStatus.PARTIAL:
        return CompletionFlowDecision(ResultStatus.PARTIAL, False, False, False, True, failure_kind or "business_insufficient", "partial")
    return CompletionFlowDecision(ResultStatus.FAILED, False, False, False, bool(retryable), failure_kind or "worker_execution_failure", "failed")


def canonicalize_completion_report(
    task: GraphAgentTask,
    *,
    result_status: ResultStatus,
    completion: dict[str, Any],
    contract_reports: list[Any],
    produced_slots: list[str],
    result_data: dict[str, Any] | None,
) -> tuple[ResultStatus, dict[str, Any], bool]:
    """Make result status and nested completion fields one authoritative state."""

    report = dict(completion or {})
    required_pairs = [
        (contract, contract_report)
        for contract, contract_report in zip(task.contracts, contract_reports)
        if str(contract.get("criticality") or "required") == "required"
    ]
    satisfied = all(
        str(getattr(contract_report, "status", "")) in {"completed", "business_empty"}
        for _, contract_report in required_pairs
    )
    business_empty = bool(
        isinstance(result_data, dict)
        and (
            result_data.get("business_empty") is True
            or result_data.get("found") is False
        )
    )
    report["contract_reports"] = [item.to_dict() for item in contract_reports]
    report["produced_information_slots"] = list(dict.fromkeys(produced_slots))
    report["missing_information_slots"] = [
        slot for slot in task.expected_output_slots if slot not in set(produced_slots)
    ]
    report["expected_task_completed"] = bool(satisfied)
    report["completion_status"] = "completed" if satisfied else "not_completed"

    if satisfied:
        status = (
            ResultStatus.PROPOSAL_READY
            if result_status == ResultStatus.PROPOSAL_READY
            else ResultStatus.COMPLETED
        )
        report.update({
            "execution_status": "succeeded",
            "contract_status": "valid",
            "business_status": "empty" if business_empty else "sufficient",
            "failure_kind": "none",
            "limitations": [],
        })
        return status, report, True

    report["contract_status"] = "not_satisfied"
    if result_status == ResultStatus.NEED_CONTEXT:
        report["execution_status"] = "need_context"
    elif result_status == ResultStatus.BLOCKED:
        report["execution_status"] = "blocked"
    elif result_status == ResultStatus.PARTIAL:
        report["execution_status"] = "partial"
    else:
        report["execution_status"] = "failed"
    if not str(report.get("failure_kind") or "").strip() or report.get("failure_kind") == "none":
        report["failure_kind"] = "worker_execution_failure"
    return result_status, report, False
