from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _plain(value: Any) -> Any:
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
class UserContext:
    user_id: str = "default"
    profile_summary: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    preference_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class ConversationContext:
    conversation_id: str = ""
    language: str = "zh"
    recent_messages: list[dict[str, Any]] = field(default_factory=list)
    active_topic: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class TaskContext:
    task_id: str = ""
    user_goal: dict[str, Any] = field(default_factory=dict)
    task_plan: dict[str, Any] = field(default_factory=dict)
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    required_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class ToolContext:
    allowed_tools: list[str] = field(default_factory=list)
    current_tool: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    result_summary: dict[str, Any] = field(default_factory=dict)
    full_result_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class PortfolioContext:
    account_summary: dict[str, Any] = field(default_factory=dict)
    positions_summary: list[dict[str, Any]] = field(default_factory=list)
    risk_summary: dict[str, Any] = field(default_factory=dict)
    raw_positions: list[dict[str, Any]] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class EvidenceContext:
    evidence_summary: list[dict[str, Any]] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    mcp_sources: list[dict[str, Any]] = field(default_factory=list)
    raw_evidence: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class ArtifactContext:
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    produced_outputs: list[str] = field(default_factory=list)
    readable_artifact_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class ApprovalContext:
    pending_plan_id: str = ""
    plan_hash: str = ""
    status: str = ""
    token_present: bool = False
    pending_plan_summary: dict[str, Any] = field(default_factory=dict)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class RuntimeContext:
    run_id: str = ""
    phase: str = ""
    business_constraints: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stack_trace: str = ""
    observation_refs: list[dict[str, Any]] = field(default_factory=list)
    blocking_observation_ids: list[str] = field(default_factory=list)
    replan_refs: list[dict[str, Any]] = field(default_factory=list)
    replan_count: int = 0
    completed_tasks: list[str] = field(default_factory=list)
    failed_tasks: list[str] = field(default_factory=list)
    pending_tasks: list[str] = field(default_factory=list)
    tool_result_refs: list[dict[str, Any]] = field(default_factory=list)
    missing_outputs: list[str] = field(default_factory=list)
    completion_status: str = ""
    latest_replan_decision_id: str = ""
    handoff_refs: list[dict[str, Any]] = field(default_factory=list)
    latest_handoff_trace_id: str = ""
    handoff_role_summaries: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class MemoryContext:
    retrieval_id: str = ""
    memory_refs: list[str] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    user_preference_refs: list[str] = field(default_factory=list)
    recent_decision_refs: list[str] = field(default_factory=list)
    candidate_count: int = 0
    threshold_pass_count: int = 0
    selected_count: int = 0
    relevance_threshold: float = 0.0
    token_budget: int = 0
    token_used: int = 0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class ContextBundle:
    """The single working-memory object for one user request / Agent run."""
    context_id: str = field(default_factory=lambda: f"context_{uuid4().hex[:12]}")
    user_id: str = "default"
    conversation_id: str = ""
    run_id: str = ""
    task_id: str = ""
    created_at: str = field(default_factory=_now_text)
    updated_at: str = field(default_factory=_now_text)
    locale: str = "zh-CN"
    user_context: UserContext = field(default_factory=UserContext)
    conversation_context: ConversationContext = field(default_factory=ConversationContext)
    task_context: TaskContext = field(default_factory=TaskContext)
    tool_context: ToolContext = field(default_factory=ToolContext)
    portfolio_context: PortfolioContext = field(default_factory=PortfolioContext)
    evidence_context: EvidenceContext = field(default_factory=EvidenceContext)
    artifact_context: ArtifactContext = field(default_factory=ArtifactContext)
    approval_context: ApprovalContext = field(default_factory=ApprovalContext)
    runtime_context: RuntimeContext = field(default_factory=RuntimeContext)
    memory_context: MemoryContext = field(default_factory=MemoryContext)
    visibility_policy: dict[str, Any] = field(default_factory=dict)
    token_budget: dict[str, int] = field(default_factory=lambda: {"max_total_tokens": 1800})
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.user_context.user_id or self.user_context.user_id == "default":
            self.user_context.user_id = self.user_id or "default"
        if not self.conversation_context.conversation_id:
            self.conversation_context.conversation_id = self.conversation_id
        if not self.task_context.task_id:
            self.task_context.task_id = self.task_id
        if not self.runtime_context.run_id:
            self.runtime_context.run_id = self.run_id
        self.metadata.setdefault("working_memory_model", "context_bundle_per_run")
        self.metadata.setdefault("working_memory_scope", "single_agent_run")

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    def to_minimal_context(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "locale": self.locale,
            "approval": {
                "pending_plan_id": self.approval_context.pending_plan_id,
                "plan_hash": self.approval_context.plan_hash,
                "status": self.approval_context.status,
                "token_present": self.approval_context.token_present,
            },
            "artifact_refs": list(self.artifact_context.artifact_refs),
            "memory": {
                "retrieval_id": self.memory_context.retrieval_id,
                "memory_refs": list(self.memory_context.memory_refs),
                "selected_count": self.memory_context.selected_count,
                "relevance_threshold": self.memory_context.relevance_threshold,
            },
            "observation_refs": list(self.runtime_context.observation_refs),
            "blocking_observation_ids": list(self.runtime_context.blocking_observation_ids),
            "latest_replan_decision_id": self.runtime_context.latest_replan_decision_id,
            "working_state": {
                "phase": self.runtime_context.phase,
                "completed_tasks": list(self.runtime_context.completed_tasks),
                "failed_tasks": list(self.runtime_context.failed_tasks),
                "pending_tasks": list(self.runtime_context.pending_tasks),
                "replan_count": self.runtime_context.replan_count,
                "missing_outputs": list(self.runtime_context.missing_outputs),
                "completion_status": self.runtime_context.completion_status,
            },
            "handoff_refs": list(self.runtime_context.handoff_refs),
            "latest_handoff_trace_id": self.runtime_context.latest_handoff_trace_id,
            "handoff_role_summaries": list(self.runtime_context.handoff_role_summaries),
            "metadata": dict(self.metadata),
        }
