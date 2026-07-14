from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {str(key): _plain(item) for key, item in asdict(value).items()}
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _plain(value.to_dict())
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, set):
        return sorted(_plain(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    return value


@dataclass
class ReActStep:
    step_id: str = field(default_factory=lambda: _id("react_step"))
    run_id: str = ""
    task_id: str = ""
    thought_summary: str = ""
    action_summary: str = ""
    tool_name: str = ""
    observation_id: str = ""
    replan_decision_id: str = ""
    status: str = "created"
    created_at: str = field(default_factory=_now_text)
    refs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ReActStep":
        return cls(**dict(value or {}))


@dataclass
class ReActTrace:
    trace_id: str = field(default_factory=lambda: _id("react_trace"))
    run_id: str = ""
    steps: list[ReActStep] = field(default_factory=list)
    message_ids: list[str] = field(default_factory=list)
    observation_ids: list[str] = field(default_factory=list)
    tool_call_edges: list[dict[str, Any]] = field(default_factory=list)
    artifact_edges: list[dict[str, Any]] = field(default_factory=list)
    approval_edges: list[dict[str, Any]] = field(default_factory=list)
    memory_edges: list[dict[str, Any]] = field(default_factory=list)
    replan_edges: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_step(self, step: ReActStep | dict[str, Any]) -> ReActStep:
        item = step if isinstance(step, ReActStep) else ReActStep.from_dict(dict(step or {}))
        if not item.run_id:
            item.run_id = self.run_id
        self.steps.append(item)
        if item.observation_id and item.observation_id not in self.observation_ids:
            self.observation_ids.append(item.observation_id)
        if item.replan_decision_id:
            self.replan_edges.append({"step_id": item.step_id, "replan_decision_id": item.replan_decision_id})
        return item

    def add_observation_edge(self, *, step_id: str, observation_id: str) -> None:
        observation_id = str(observation_id or "")
        if observation_id and observation_id not in self.observation_ids:
            self.observation_ids.append(observation_id)
        for step in self.steps:
            if step.step_id == str(step_id):
                step.observation_id = observation_id
                break

    def add_tool_call_edge(self, *, step_id: str, tool_call_id: str, tool_name: str = "") -> None:
        self.tool_call_edges.append({"step_id": step_id, "tool_call_id": tool_call_id, "tool_name": tool_name})

    def add_artifact_edge(self, *, step_id: str, artifact_id: str) -> None:
        self.artifact_edges.append({"step_id": step_id, "artifact_id": artifact_id})

    def add_approval_edge(self, *, step_id: str, plan_id: str, status: str = "") -> None:
        self.approval_edges.append({"step_id": step_id, "plan_id": plan_id, "status": status})

    def add_memory_edge(self, *, step_id: str, memory_id: str) -> None:
        self.memory_edges.append({"step_id": step_id, "memory_id": memory_id})

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ReActTrace":
        data = dict(value or {})
        data["steps"] = [ReActStep.from_dict(item) for item in data.get("steps") or []]
        return cls(**data)
