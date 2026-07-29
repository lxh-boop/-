"""Contracts for one Worker's capability-scoped private-tool DAG."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _strings(value: Any, *, limit: int = 30) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    for item in list(value)[:limit]:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


@dataclass
class WorkerPlanStep:
    step_id: str
    tool_name: str
    objective: str
    dependency_step_ids: list[str] = field(default_factory=list)
    required_outputs: list[str] = field(default_factory=list)
    proposed_arguments: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.step_id = str(self.step_id or "").strip()
        self.tool_name = str(self.tool_name or "").strip()
        self.objective = str(self.objective or "").strip()
        self.dependency_step_ids = _strings(
            self.dependency_step_ids,
            limit=20,
        )
        self.required_outputs = _strings(self.required_outputs, limit=30)
        self.proposed_arguments = dict(self.proposed_arguments or {})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkerPlanStep":
        return cls(**dict(value or {}))


@dataclass
class WorkerExecutionPlan:
    capability_id: str
    steps: list[WorkerPlanStep]
    plan_version: str = "worker_tool_plan.v1"

    def __post_init__(self) -> None:
        self.capability_id = str(self.capability_id or "").strip()
        self.steps = [
            item
            if isinstance(item, WorkerPlanStep)
            else WorkerPlanStep.from_dict(item)
            for item in list(self.steps or [])[:12]
            if isinstance(item, (WorkerPlanStep, dict))
        ]
        self.plan_version = "worker_tool_plan.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_version": self.plan_version,
            "capability_id": self.capability_id,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkerExecutionPlan":
        return cls(**dict(value or {}))


__all__ = [
    "WorkerExecutionPlan",
    "WorkerPlanStep",
]
