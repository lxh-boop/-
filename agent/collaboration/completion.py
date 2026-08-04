"""Structured Worker completion contracts and flow decisions.

This module deliberately separates three concerns:

1. output schemas define the required JSON shape;
2. Workers/LLMs return a structured completion report against the current task;
3. coordinator rules only route the program from that report.

The coordinator does not infer business completion from summaries, list lengths, or
free-form text. LLM-based Workers are constrained by prompt, structured input,
structured output, and schema validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import GraphAgentTask, ResultStatus, WorkerTaskContract
from .worker_contracts import (
    WorkerContractViolation,
    completion_report_schema,
    validate_schema,
)


COMPLETION_CONTRACT_VERSION = "worker-completion-contract.v1"
COMPLETION_REPORT_VERSION = "worker-completion-report.v1"


@dataclass(frozen=True)
class CompletionFlowDecision:
    """Program-flow decision compiled from a validated completion report."""

    result_status: ResultStatus
    semantic_satisfied: bool
    should_freeze: bool
    reusable: bool
    replan_recommended: bool
    failure_kind: str
    freeze_reason: str


def _object_branch(schema: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}
    if schema.get("type") == "object":
        return schema
    for key in ("anyOf", "oneOf"):
        for item in schema.get(key) or []:
            if isinstance(item, dict) and item.get("type") == "object":
                return item
    return {}


def _required_paths(schema: dict[str, Any], *, prefix: str = "") -> list[str]:
    """Return required object paths from the declared JSON schema.

    This is structural only. It does not decide whether a non-empty value is
    semantically sufficient for the user's goal.
    """

    branch = _object_branch(schema)
    if not branch:
        return []
    properties = branch.get("properties") if isinstance(branch.get("properties"), dict) else {}
    required = branch.get("required") if isinstance(branch.get("required"), list) else []
    paths: list[str] = []
    for name in required:
        key = str(name)
        path = f"{prefix}.{key}" if prefix else key
        paths.append(path)
        child = properties.get(key)
        if isinstance(child, dict):
            paths.extend(_required_paths(child, prefix=path))
    return list(dict.fromkeys(paths))


def required_result_fields(output_schema: dict[str, Any]) -> list[str]:
    """Resolve required business-payload fields from a WorkerResult schema."""

    root = _object_branch(output_schema)
    properties = root.get("properties") if isinstance(root.get("properties"), dict) else {}
    data_schema = properties.get("data") if isinstance(properties.get("data"), dict) else {}
    return _required_paths(data_schema, prefix="data")


def compile_completion_contract(
    task: GraphAgentTask,
    task_contract: WorkerTaskContract,
) -> dict[str, Any]:
    """Compile the task completion contract from registered schemas and task goals.

    MainAgent/Worker LLMs never choose required field names. Required payload
    fields come from the registered output schema; required information slots and
    criteria come from the already accepted Worker task contract.
    """

    required_slots = [
        str(item)
        for item in dict(task.expected_output or {}).get("information_slots") or []
        if str(item or "").strip()
    ]
    criteria = [
        {"criterion_id": f"C{index:02d}", "description": str(text)}
        for index, text in enumerate(task.completion_criteria or task_contract.completion_criteria, start=1)
        if str(text or "").strip()
    ]
    return {
        "schema_version": COMPLETION_CONTRACT_VERSION,
        "output_type": str(task.expected_output_type or task_contract.output_type or ""),
        "required_result_fields": required_result_fields(task_contract.output_schema),
        "required_information_slots": list(dict.fromkeys(required_slots)),
        "criteria": criteria,
        "flow_policy": {
            "completed": "unlock_downstream",
            "partially_completed": "pause_and_replan",
            "not_completed": "pause_and_replan",
            "failed": "pause_and_replan",
            "blocked": "pause_and_replan",
            "need_context": "pause_and_request_context",
        },
        "completion_report_required": True,
        "completion_report_source": str(task_contract.completion_report_source or "runtime"),
        "access_mode": getattr(task_contract.access_mode, "value", str(task_contract.access_mode or "read")),
    }


def _expected_criterion_ids(contract: dict[str, Any]) -> list[str]:
    return [
        str(item.get("criterion_id") or "")
        for item in contract.get("criteria") or []
        if isinstance(item, dict) and str(item.get("criterion_id") or "")
    ]


def validate_completion_report(
    report: dict[str, Any],
    contract: dict[str, Any],
    *,
    path: str = "$.completion",
) -> None:
    """Validate only structure and internal consistency.

    This function does not decide whether a financial conclusion is correct. It
    checks that the Worker/LLM evaluated every declared criterion and returned a
    self-consistent structured result that the program can route.
    """

    validate_schema(report, completion_report_schema(), path=path)
    if str(report.get("schema_version") or "") != COMPLETION_REPORT_VERSION:
        raise WorkerContractViolation(
            "completion_report_version_mismatch",
            f"{path}.schema_version",
            str(report.get("schema_version") or ""),
        )
    expected_output_type = str(contract.get("output_type") or "")
    if str(report.get("output_type") or "") != expected_output_type:
        raise WorkerContractViolation(
            "completion_output_type_mismatch",
            f"{path}.output_type",
            f"expected={expected_output_type},actual={report.get('output_type')}",
        )

    required_slots = set(str(item) for item in contract.get("required_information_slots") or [])
    produced = set(str(item) for item in report.get("produced_information_slots") or [])
    missing = set(str(item) for item in report.get("missing_information_slots") or [])
    unknown = sorted((produced | missing) - required_slots)
    if unknown:
        raise WorkerContractViolation(
            "completion_report_unknown_information_slot",
            path,
            ",".join(unknown),
        )
    if produced & missing:
        raise WorkerContractViolation(
            "completion_report_slot_overlap",
            path,
            ",".join(sorted(produced & missing)),
        )
    if required_slots and produced | missing != required_slots:
        absent = sorted(required_slots - produced - missing)
        raise WorkerContractViolation(
            "completion_report_slot_partition_incomplete",
            path,
            ",".join(absent),
        )

    expected_ids = _expected_criterion_ids(contract)
    actual_rows = report.get("criteria") or []
    actual_ids = [str(item.get("criterion_id") or "") for item in actual_rows if isinstance(item, dict)]
    if actual_ids != expected_ids:
        raise WorkerContractViolation(
            "completion_report_criteria_mismatch",
            f"{path}.criteria",
            f"expected={expected_ids},actual={actual_ids}",
        )

    completed = bool(report.get("expected_task_completed"))
    completion_status = str(report.get("completion_status") or "")
    all_criteria_satisfied = all(bool(item.get("satisfied")) for item in actual_rows)
    if completed:
        if completion_status != "completed":
            raise WorkerContractViolation(
                "completed_report_requires_completed_status",
                f"{path}.completion_status",
            )
        if missing:
            raise WorkerContractViolation(
                "completed_report_cannot_have_missing_slots",
                f"{path}.missing_information_slots",
            )
        if not all_criteria_satisfied:
            raise WorkerContractViolation(
                "completed_report_requires_all_criteria",
                f"{path}.criteria",
            )
    elif completion_status == "completed":
        raise WorkerContractViolation(
            "incomplete_report_cannot_use_completed_status",
            f"{path}.completion_status",
        )


def non_success_completion_report(
    task: GraphAgentTask,
    *,
    execution_status: str,
    reason: str,
    failure_kind: str,
) -> dict[str, Any]:
    contract = dict(task.completion_contract or {})
    required_slots = [str(item) for item in contract.get("required_information_slots") or []]
    return {
        "schema_version": COMPLETION_REPORT_VERSION,
        "report_source": "runtime",
        "execution_status": str(execution_status),
        "contract_status": "not_evaluated",
        "business_status": "unknown",
        "completion_status": "not_completed",
        "expected_task_completed": False,
        "output_type": str(task.expected_output_type or contract.get("output_type") or ""),
        "produced_information_slots": [],
        "missing_information_slots": required_slots,
        "criteria": [
            {
                "criterion_id": str(item.get("criterion_id") or ""),
                "satisfied": False,
                "reason": str(reason)[:1000],
                "source_refs": [],
            }
            for item in contract.get("criteria") or []
            if isinstance(item, dict)
        ],
        "limitations": [str(reason)[:1000]],
        "failure_kind": str(failure_kind),
    }


def build_completion_report(
    task: GraphAgentTask,
    *,
    execution_status: str,
    contract_status: str,
    business_status: str,
    completion_status: str,
    expected_task_completed: bool,
    produced_information_slots: list[str],
    criterion_results: list[dict[str, Any]],
    limitations: list[str] | None = None,
    failure_kind: str = "none",
    report_source: str = "runtime",
) -> dict[str, Any]:
    contract = dict(task.completion_contract or {})
    required_slots = [str(item) for item in contract.get("required_information_slots") or []]
    produced = list(dict.fromkeys(str(item) for item in produced_information_slots if str(item)))
    missing = [item for item in required_slots if item not in set(produced)]
    report = {
        "schema_version": COMPLETION_REPORT_VERSION,
        "report_source": str(report_source or "runtime"),
        "execution_status": str(execution_status),
        "contract_status": str(contract_status),
        "business_status": str(business_status),
        "completion_status": str(completion_status),
        "expected_task_completed": bool(expected_task_completed),
        "output_type": str(task.expected_output_type or contract.get("output_type") or ""),
        "produced_information_slots": produced,
        "missing_information_slots": missing,
        "criteria": [dict(item) for item in criterion_results],
        "limitations": [str(item) for item in limitations or [] if str(item).strip()],
        "failure_kind": str(failure_kind or "none"),
    }
    validate_completion_report(report, contract)
    return report



def runtime_completion_report(
    task: GraphAgentTask,
    task_contract: WorkerTaskContract,
    *,
    result_status: ResultStatus,
    output_type: str,
    data: dict[str, Any] | None,
    error: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a completion report for a deterministic/tool Worker.

    The runtime does not interpret free-form financial text. It reports the
    structured status returned by the Worker adapter, validates the registered
    output shape elsewhere, and maps the task's declared information slots.
    """

    success = result_status in {ResultStatus.COMPLETED, ResultStatus.PROPOSAL_READY}
    business_empty = bool(
        isinstance(data, dict)
        and (
            data.get("business_empty") is True
            or data.get("found") is False
            or data.get("status") in {"empty", "business_empty"}
        )
    )
    contract = dict(task.completion_contract or compile_completion_contract(task, task_contract))
    task.completion_contract = contract
    produced = list(contract.get("required_information_slots") or []) if success else []
    criteria = [
        {
            "criterion_id": str(item.get("criterion_id") or ""),
            "satisfied": bool(success),
            "reason": (
                "Registered output schema and deterministic Worker result were validated."
                if success
                else str((error or {}).get("message") or "Deterministic Worker did not complete.")
            )[:1000],
            "source_refs": [f"worker_result:{task.task_id}"] if success else [],
        }
        for item in contract.get("criteria") or []
        if isinstance(item, dict)
    ]
    return build_completion_report(
        task,
        execution_status=(
            "succeeded" if success else
            "need_context" if result_status == ResultStatus.NEED_CONTEXT else
            "blocked" if result_status == ResultStatus.BLOCKED else
            "failed"
        ),
        contract_status="valid" if success else "not_evaluated",
        business_status="empty" if business_empty else ("sufficient" if success else "unknown"),
        completion_status="completed" if success else "not_completed",
        expected_task_completed=success,
        produced_information_slots=produced,
        criterion_results=criteria,
        limitations=[] if success else [str((error or {}).get("message") or "Worker did not complete.")],
        failure_kind="none" if success else str((error or {}).get("code") or "worker_execution_failure"),
        report_source="runtime",
    )


def flow_decision(
    result_status: ResultStatus,
    completion: dict[str, Any],
    *,
    output_type: str,
    retryable: bool,
) -> CompletionFlowDecision:
    """Translate validated Worker output into program flow only."""

    expected_completed = bool(completion.get("expected_task_completed"))
    completion_status = str(completion.get("completion_status") or "not_completed")
    execution_status = str(completion.get("execution_status") or "failed")
    failure_kind = str(completion.get("failure_kind") or "none")

    if result_status == ResultStatus.NEED_CONTEXT or execution_status == "need_context":
        return CompletionFlowDecision(
            ResultStatus.NEED_CONTEXT, False, False, False, False,
            "context_missing", "context_required_before_resume",
        )
    if result_status == ResultStatus.BLOCKED or execution_status == "blocked":
        return CompletionFlowDecision(
            ResultStatus.BLOCKED, False, False, False, True,
            "upstream_worker_failed", "blocked_branch_waits_for_replan",
        )
    if result_status in {ResultStatus.FAILED, ResultStatus.NOT_EXECUTED} or execution_status == "failed":
        return CompletionFlowDecision(
            ResultStatus.FAILED,
            False,
            not retryable,
            False,
            bool(retryable),
            failure_kind if failure_kind != "none" else "worker_execution_failure",
            "non_retryable_failure_frozen" if not retryable else "retryable_failure_requires_replan",
        )
    if expected_completed and completion_status == "completed":
        status = ResultStatus.PROPOSAL_READY if result_status == ResultStatus.PROPOSAL_READY else ResultStatus.COMPLETED
        reusable = output_type != "FinalReport"
        return CompletionFlowDecision(
            status, True, reusable, reusable, False,
            "none", "worker_completion_report_satisfied",
        )
    return CompletionFlowDecision(
        ResultStatus.PARTIAL,
        False,
        False,
        False,
        True,
        failure_kind if failure_kind != "none" else "business_result_insufficient",
        "completion_report_requires_replan",
    )


__all__ = [
    "COMPLETION_CONTRACT_VERSION",
    "COMPLETION_REPORT_VERSION",
    "CompletionFlowDecision",
    "build_completion_report",
    "compile_completion_contract",
    "flow_decision",
    "non_success_completion_report",
    "required_result_fields",
    "runtime_completion_report",
    "validate_completion_report",
]
