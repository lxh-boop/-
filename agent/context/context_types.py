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
    business_data: list[dict[str, Any]] = field(default_factory=list)
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

    @staticmethod
    def _business_entity_id(entity_ref: dict[str, Any] | None) -> str:
        ref = dict(entity_ref or {})
        return str(ref.get("node_id") or "__run__")

    def put_business_data(
        self,
        *,
        entity_ref: dict[str, Any] | None,
        name: str,
        value: Any,
        data_time: str = "",
        contract: str = "",
        version: str = "1.0",
        schema_id: str = "",
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append one successfully queried/generated business-data item.

        The label is only the business data name.  Empty values are retained
        because the presence of the label itself means the query completed.
        Failed Worker/Tool paths never call this method.
        """
        data_name = str(name or "").strip()
        if not data_name:
            raise ValueError("business_data_name_required")
        ref = dict(entity_ref or {})
        contract_id = str(contract or data_name).strip()
        contract_version = str(version or "1.0").strip()
        item = {
            "entity_ref": ref,
            "entity_id": self._business_entity_id(ref),
            "name": data_name,
            "value": _plain(value),
            "data_time": str(data_time or ""),
            "contract": contract_id,
            "version": contract_version,
            "schema_id": str(schema_id or f"{contract_id}@{contract_version}"),
            "provenance": _plain(dict(provenance or {})),
            "created_at": _now_text(),
        }
        self.business_data.append(item)
        self.updated_at = _now_text()
        return dict(item)

    def business_data_context(
        self,
        *,
        entity_refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Return the latest entity+name values from this run working memory."""
        refs = [
            dict(ref) for ref in list(entity_refs or [])
            if isinstance(ref, dict) and str(ref.get("node_id") or "")
        ]
        wanted_ids = {str(ref.get("node_id") or "") for ref in refs}
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for raw in list(self.business_data or []):
            if not isinstance(raw, dict):
                continue
            entity_id = str(raw.get("entity_id") or self._business_entity_id(raw.get("entity_ref")))
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            if wanted_ids and entity_id not in wanted_ids and entity_id != "__run__":
                continue
            latest[(entity_id, name)] = dict(raw)

        if not refs:
            inferred: dict[str, dict[str, Any]] = {}
            for (entity_id, _), row in latest.items():
                if entity_id != "__run__" and isinstance(row.get("entity_ref"), dict):
                    inferred[entity_id] = dict(row.get("entity_ref") or {})
            refs = list(inferred.values())

        entities: list[dict[str, Any]] = []
        for ref in refs:
            entity_id = str(ref.get("node_id") or "")
            data = {
                name: row.get("value")
                for (row_entity, name), row in latest.items()
                if row_entity == entity_id
            }
            contracts = {
                name: {
                    "contract": str(row.get("contract") or name),
                    "version": str(row.get("version") or "1.0"),
                    "schema_id": str(
                        row.get("schema_id")
                        or f"{row.get('contract') or name}@{row.get('version') or '1.0'}"
                    ),
                    "provenance": _plain(dict(row.get("provenance") or {})),
                }
                for (row_entity, name), row in latest.items()
                if row_entity == entity_id
            }
            # An entity with only empty values is still included: the labels
            # prove those queries completed.
            if data:
                entities.append(
                    {
                        "entity_ref": dict(ref),
                        "data": data,
                        "contracts": contracts,
                    }
                )

        global_data = {
            name: row.get("value")
            for (row_entity, name), row in latest.items()
            if row_entity == "__run__"
        }
        global_contracts = {
            name: {
                "contract": str(row.get("contract") or name),
                "version": str(row.get("version") or "1.0"),
                "schema_id": str(
                    row.get("schema_id")
                    or f"{row.get('contract') or name}@{row.get('version') or '1.0'}"
                ),
                "provenance": _plain(dict(row.get("provenance") or {})),
            }
            for (row_entity, name), row in latest.items()
            if row_entity == "__run__"
        }
        return {
            "schema_version": "context_bundle_business_data.v2",
            "run_id": str(self.run_id or ""),
            "entities": entities,
            "global_data": global_data,
            "global_contracts": global_contracts,
            "available_names": sorted({name for (_, name) in latest}),
        }

    def has_business_data(self, *, entity_id: str, name: str) -> bool:
        target_entity = str(entity_id or "__run__")
        target_name = str(name or "").strip()
        return any(
            str(item.get("entity_id") or self._business_entity_id(item.get("entity_ref"))) == target_entity
            and str(item.get("name") or "") == target_name
            for item in list(self.business_data or [])
            if isinstance(item, dict)
        )

    def missing_business_data_entities(
        self,
        *,
        entity_refs: list[Any],
        names: list[str],
    ) -> list[Any]:
        required = [str(name) for name in names if str(name)]
        if not required:
            return []
        missing: list[Any] = []
        for ref in list(entity_refs or []):
            entity_id = str(getattr(ref, "node_id", "") or (ref.get("node_id") if isinstance(ref, dict) else ""))
            if not entity_id:
                continue
            if any(
                not self.has_business_data(entity_id=entity_id, name=name)
                and not self.has_business_data(entity_id="__run__", name=name)
                for name in required
            ):
                missing.append(ref)
        return missing

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
            "business_data_names": sorted({
                str(item.get("name") or "")
                for item in self.business_data
                if isinstance(item, dict) and str(item.get("name") or "")
            }),
            "metadata": dict(self.metadata),
        }
