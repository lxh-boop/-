"""Contracts for Main-Agent capability discovery and planning."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _string_list(value: Any, *, limit: int = 50) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    for item in list(value)[:limit]:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


@dataclass(frozen=True)
class WorkerCapability:
    """One business capability exposed to the Main Agent.

    ``task_type`` is an internal Worker binding and is deliberately omitted
    from the coordinator-safe view.
    """

    capability_id: str
    task_type: str
    description: str
    when_to_use: str
    not_for: str = ""
    request_modes: list[str] = field(default_factory=lambda: ["analysis"])
    required_dependency_output_types: list[str] = field(default_factory=list)
    accepted_dependency_output_types: list[str] = field(default_factory=list)
    produced_output_types: list[str] = field(default_factory=list)
    supports_parallel: bool = True
    can_finalize: bool = False
    side_effect_scope: str = "read_only"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def safe_for_coordinator(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "description": self.description,
            "when_to_use": self.when_to_use,
            "not_for": self.not_for,
            "request_modes": list(self.request_modes),
            "required_dependency_output_types": list(
                self.required_dependency_output_types
            ),
            "accepted_dependency_output_types": list(
                self.accepted_dependency_output_types
            ),
            "produced_output_types": list(self.produced_output_types),
            "supports_parallel": self.supports_parallel,
            "can_finalize": self.can_finalize,
            "side_effect_scope": self.side_effect_scope,
        }


@dataclass(frozen=True)
class AgentCapabilityCard:
    """Private Worker binding plus its coordinator-safe capability cards."""

    agent_id: str
    role: str
    description: str
    capabilities: list[WorkerCapability] = field(default_factory=list)

    @property
    def accepted_task_types(self) -> list[str]:
        return [capability.task_type for capability in self.capabilities]

    @property
    def output_types(self) -> list[str]:
        return sorted(
            {
                output_type
                for capability in self.capabilities
                for output_type in capability.produced_output_types
            }
        )

    @property
    def supports_parallel(self) -> bool:
        return all(capability.supports_parallel for capability in self.capabilities)

    @property
    def can_generate_proposal(self) -> bool:
        return any(
            "proposal" in capability.produced_output_types
            for capability in self.capabilities
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def safe_for_coordinator(self) -> dict[str, Any]:
        return {
            "worker_scope": self.description,
            "capabilities": [
                capability.safe_for_coordinator()
                for capability in self.capabilities
            ],
        }


@dataclass
class CapabilityTaskPlan:
    """Main-Agent plan before a capability is bound to a Worker runtime."""

    task_id: str
    capability_id: str
    objective: str
    dependency_task_ids: list[str] = field(default_factory=list)
    required_outputs: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    priority: int = 1

    def __post_init__(self) -> None:
        self.task_id = str(self.task_id or "").strip()
        self.capability_id = str(self.capability_id or "").strip()
        self.objective = str(self.objective or "").strip()
        self.dependency_task_ids = _string_list(
            self.dependency_task_ids,
            limit=50,
        )
        self.required_outputs = _string_list(self.required_outputs, limit=50)
        self.constraints = _string_list(self.constraints, limit=50)
        try:
            self.priority = max(0, min(10, int(self.priority)))
        except (TypeError, ValueError):
            self.priority = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CapabilityTaskPlan":
        return cls(**dict(value or {}))


__all__ = [
    "AgentCapabilityCard",
    "CapabilityTaskPlan",
    "WorkerCapability",
]
