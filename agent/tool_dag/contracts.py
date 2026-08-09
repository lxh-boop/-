"""Typed contracts for Worker-private Tool DAG planning and execution.

The contracts are intentionally independent from Worker DAG contracts. MainAgent
never receives private Tool identifiers or Tool DAG plans. V2 adds one unified
node execution record for succeeded, failed, blocked, and pending Tool nodes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


TOOL_DAG_SCHEMA_VERSION = "worker-tool-dag.v2"
TOOL_NODE_RECORD_SCHEMA_VERSION = "tool-node-execution-record.v1"


class ToolDagContractViolation(ValueError):
    """Raised when a Worker-private Tool DAG violates a deterministic contract."""

    def __init__(self, code: str, path: str = "", detail: str = "") -> None:
        self.code = str(code or "tool_dag_contract_violation")
        self.path = str(path or "")
        self.detail = str(detail or "")
        message = self.code
        if self.path:
            message += f"@{self.path}"
        if self.detail:
            message += f":{self.detail}"
        super().__init__(message)


@dataclass(frozen=True)
class ToolDagTask:
    tool_task_id: str
    tool_name: str
    objective: str
    args: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)
    expected_output_keys: list[str] = field(default_factory=list)
    priority: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def planning_dict(self) -> dict[str, Any]:
        """LLM-visible task fields. Required outputs are compiled from Tool schema."""

        return {
            "tool_task_id": self.tool_task_id,
            "tool_name": self.tool_name,
            "objective": self.objective,
            "args": dict(self.args),
            "inputs": dict(self.inputs),
            "priority": self.priority,
        }


@dataclass(frozen=True)
class ToolDagPlan:
    worker_task_id: str
    worker_role: str
    goal_contract: dict[str, Any]
    tasks: list[ToolDagTask]
    final_output_task_ids: list[str]
    schema_version: str = TOOL_DAG_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "worker_task_id": self.worker_task_id,
            "worker_role": self.worker_role,
            "goal_contract": dict(self.goal_contract or {}),
            "tasks": [task.to_dict() for task in self.tasks],
            "final_output_task_ids": list(self.final_output_task_ids),
        }


@dataclass(frozen=True)
class ToolNodeExecutionRecord:
    """One structure used for every Tool node state exposed to local Replan.

    ``should_freeze`` is deterministic runtime output. A frozen successful node
    may be reused through ``result_ref``. A frozen non-retryable failed node is
    not reusable, but its failure fact cannot be erased or retried by the LLM.
    """

    tool_task_id: str
    tool_name: str
    objective: str
    status: str
    depends_on: list[str] = field(default_factory=list)
    execution_success: bool = False
    contract_valid: bool = False
    completion_status: str = "not_completed"
    business_status: str = "unknown"
    produced_output_keys: list[str] = field(default_factory=list)
    missing_output_keys: list[str] = field(default_factory=list)
    result_ref: str = ""
    result_summary: dict[str, Any] = field(default_factory=dict)
    should_freeze: bool = False
    freeze_reason: str = ""
    reusable: bool = False
    retryable: bool = False
    failure: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    schema_version: str = TOOL_NODE_RECORD_SCHEMA_VERSION

    @property
    def success(self) -> bool:
        """Return whether this node completed and validated successfully."""

        return bool(
            self.status == "succeeded"
            and self.execution_success
            and self.contract_valid
            and self.completion_status == "completed"
        )

    @property
    def failure_kind(self) -> str:
        return str((self.failure or {}).get("failure_kind") or "")

    @property
    def error_type(self) -> str:
        return str((self.failure or {}).get("error_id") or (self.failure or {}).get("error_type") or "")

    @property
    def error_message(self) -> str:
        return str((self.failure or {}).get("reason") or (self.failure or {}).get("error_message") or "")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)



@dataclass(frozen=True)
class ToolDagExecutionResult:
    plan: ToolDagPlan
    results: dict[str, Any]
    node_records: list[ToolNodeExecutionRecord]
    execution_batches: list[list[str]]
    final_output_task_ids: list[str]
    final_results: list[Any]
    success: bool
    replan_count: int = 0
    replan_audit: list[dict[str, Any]] = field(default_factory=list)


    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "node_records": [item.to_dict() for item in self.node_records],
            "execution_batches": [list(batch) for batch in self.execution_batches],
            "final_output_task_ids": list(self.final_output_task_ids),
            "success": bool(self.success),
            "replan_count": int(self.replan_count),
            "replan_audit": [dict(item) for item in self.replan_audit],
        }


_CONTEXT_REF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"from_context": {"type": "string"}},
    "required": ["from_context"],
    "additionalProperties": False,
}

_TOOL_RESULT_REF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "from_tool_task_id": {"type": "string"},
        "output_slot": {"type": "string"},
    },
    "required": ["from_tool_task_id"],
    "additionalProperties": False,
}

_INPUT_BINDING_SCHEMA: dict[str, Any] = {
    "oneOf": [
        _CONTEXT_REF_SCHEMA,
        _TOOL_RESULT_REF_SCHEMA,
        {
            "type": "array",
            "items": {
                "oneOf": [_CONTEXT_REF_SCHEMA, _TOOL_RESULT_REF_SCHEMA],
            },
            "minItems": 1,
        },
    ]
}


TOOL_DAG_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tool_task_id": {"type": "string"},
                    "tool_name": {"type": "string"},
                    "objective": {"type": "string"},
                    "args": {"type": "object"},
                    "inputs": {
                        "type": "object",
                        "additionalProperties": _INPUT_BINDING_SCHEMA,
                    },
                    "priority": {"type": "integer"},
                },
                "required": [
                    "tool_task_id",
                    "tool_name",
                    "objective",
                    "args",
                    "inputs",
                    "priority",
                ],
                "additionalProperties": False,
            },
            "minItems": 1,
        },
        "final_output_task_ids": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
    },
    "required": ["tasks", "final_output_task_ids"],
    "additionalProperties": False,
}



__all__ = [
    "TOOL_DAG_OUTPUT_SCHEMA",
    "TOOL_DAG_SCHEMA_VERSION",
    "TOOL_NODE_RECORD_SCHEMA_VERSION",
    "ToolDagContractViolation",
    "ToolDagExecutionResult",
    "ToolDagPlan",
    "ToolDagTask",
    "ToolNodeExecutionRecord",
]
