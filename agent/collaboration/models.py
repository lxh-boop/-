from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.graph.contracts import GraphPatch, GraphPathRef, GraphRef, refs_from


def now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {str(key): _plain(item) for key, item in asdict(value).items()}
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _plain(value.to_dict())
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _str_list(value: Any, *, limit: int = 100) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    for item in list(value)[:limit]:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _dict_list(value: Any, *, limit: int = 100) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in list(value)[:limit] if isinstance(item, dict)]


def _task_inputs(value: Any, *, limit_roles: int = 20, limit_items: int = 20) -> dict[str, list[dict[str, str]]]:
    """Normalize semantic upstream input bindings.

    MainAgent declares only semantic roles and ``from_task_id`` references.
    Runtime execution dependencies are derived later from this normalized map.
    """

    if not isinstance(value, dict):
        return {}
    result: dict[str, list[dict[str, str]]] = {}
    for raw_role, raw_items in list(value.items())[:limit_roles]:
        role = str(raw_role or "").strip()
        if not role:
            continue
        items = raw_items if isinstance(raw_items, list) else [raw_items]
        normalized: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for raw_item in items[:limit_items]:
            if not isinstance(raw_item, dict):
                continue
            task_id = str(raw_item.get("from_task_id") or "").strip()
            output_type = str(raw_item.get("expected_output_type") or "").strip()
            if not task_id:
                continue
            key = (task_id, output_type)
            if key in seen:
                continue
            seen.add(key)
            normalized.append(
                {
                    "from_task_id": task_id,
                    "expected_output_type": output_type,
                }
            )
        if normalized:
            result[role] = normalized
    return result


def _compact(value: Any, *, depth: int = 0, max_depth: int = 5, max_items: int = 20, max_chars: int = 1200) -> Any:
    if depth >= max_depth:
        return "<summarized>" if isinstance(value, (dict, list, tuple, set)) else str(value)[:max_chars]
    if isinstance(value, str):
        return value[:max_chars] + ("…" if len(value) > max_chars else "")
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        blocked = {
            "raw_payload", "raw_tool_payload", "tool_calls", "arguments", "sql",
            "traceback", "stack_trace", "confirmation_token", "confirmation_token_hash",
            "api_key", "password", "secret", "private_chain_of_thought", "chain_of_thought",
            "reasoning_content", "content", "body", "full_text",
        }
        return {
            str(key): _compact(item, depth=depth + 1, max_depth=max_depth, max_items=max_items, max_chars=max_chars)
            for key, item in list(value.items())[:max_items]
            if str(key).lower() not in blocked
        }
    if isinstance(value, (list, tuple, set)):
        return [
            _compact(item, depth=depth + 1, max_depth=max_depth, max_items=max_items, max_chars=max_chars)
            for item in list(value)[:max_items]
        ]
    return str(value)[:max_chars]


def _public_result_data(output_type: str, data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the coordinator-visible Worker payload.

    Generic evidence payloads continue to remove fields such as ``content``,
    ``body`` and ``full_text`` because those fields may contain raw documents.
    ``FinalReport.content`` is different: it is the deliberate user-facing
    product of the report Worker and is required by the public FinalReport
    schema. Preserve only that schema-owned field after the generic compaction.
    """
    if data is None:
        return None

    compacted = _compact(data, max_depth=5)
    result = dict(compacted) if isinstance(compacted, dict) else {}
    if str(output_type or "") == "FinalReport":
        report_content = str(data.get("content") or "")
        result["content"] = _compact(
            report_content,
            max_depth=2,
            max_chars=12000,
        )
    return result


def _semantic_inputs_schema(
    bindings: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    """Build the public schema for upstream WorkerResult references only.

    This schema is intentionally separate from ``args_schema``.  Values under
    semantic inputs are references to upstream tasks, never direct strings,
    numbers, GraphRef IDs, user IDs, language values, or time values.
    """

    properties: dict[str, Any] = {}
    required: list[str] = []
    for raw_role, raw_binding in dict(bindings or {}).items():
        role = str(raw_role or "").strip()
        if not role:
            continue
        binding = dict(raw_binding or {})
        accepted = [
            str(item)
            for item in binding.get("accepted_output_types") or []
            if str(item or "").strip()
        ]
        output_type_schema: dict[str, Any] = {
            "type": "string",
            "minLength": 1,
        }
        if accepted and "*" not in accepted:
            output_type_schema["enum"] = accepted
        reference_schema = {
            "type": "object",
            "properties": {
                "from_task_id": {"type": "string", "minLength": 1},
                "expected_output_type": output_type_schema,
            },
            "required": ["from_task_id", "expected_output_type"],
            "additionalProperties": False,
        }
        minimum = max(0, int(binding.get("min_items") or 0))
        maximum = max(minimum, int(binding.get("max_items") or 8))
        if bool(binding.get("required")) and minimum == 0:
            minimum = 1
        properties[role] = {
            "description": str(binding.get("description") or ""),
            "anyOf": [
                reference_schema,
                {
                    "type": "array",
                    "items": reference_schema,
                    "minItems": max(1, minimum),
                    "maxItems": maximum,
                },
            ],
        }
        if bool(binding.get("required")):
            required.append(role)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


class TaskStatus(str, Enum):
    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    WAITING_CONTEXT = "waiting_context"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def from_value(cls, value: Any) -> "TaskStatus":
        if isinstance(value, cls):
            return value
        text = str(value or "created").strip().lower()
        for item in cls:
            if item.value == text:
                return item
        return cls.CREATED


class ResultStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    NEED_CONTEXT = "need_context"
    NOT_EXECUTED = "not_executed"
    FAILED = "failed"
    BLOCKED = "blocked"
    WAITING_APPROVAL = "waiting_approval"
    PROPOSAL_READY = "proposal_ready"

    @classmethod
    def from_value(cls, value: Any) -> "ResultStatus":
        if isinstance(value, cls):
            return value
        text = str(value or "failed").strip().lower()
        for item in cls:
            if item.value == text:
                return item
        return cls.FAILED


@dataclass(frozen=True)
class WorkerTaskContract:
    """Task-specific public and private contract owned by one Worker.

    A Worker may expose several business task types while retaining one stable
    Worker identity.  MainAgent sees only the public schema; private tool IDs
    remain inside the assigned Worker runtime.
    """

    task_type: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    default_args: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    output_type: str = ""
    upstream_input_bindings: dict[str, dict[str, Any]] = field(default_factory=dict)
    authoritative_arg_bindings: dict[str, str] = field(default_factory=dict, repr=False)
    selection_requirements: list[str] = field(default_factory=list)
    private_tool_ids: list[str] = field(default_factory=list, repr=False)

    @property
    def args_schema(self) -> dict[str, Any]:
        """Canonical direct-argument schema; ``input_schema`` is legacy internal naming."""

        return self.input_schema

    @property
    def semantic_inputs_schema(self) -> dict[str, Any]:
        return _semantic_inputs_schema(self.upstream_input_bindings)

    def safe_for_coordinator(self) -> dict[str, Any]:
        public_args_schema = _plain(self.args_schema)
        runtime_bound = set(self.authoritative_arg_bindings)
        if isinstance(public_args_schema, dict):
            required = public_args_schema.get("required")
            if isinstance(required, list):
                public_args_schema["required"] = [
                    str(item) for item in required if str(item) not in runtime_bound
                ]
            public_args_schema["x-runtime-bound-args"] = sorted(runtime_bound)
        return {
            "task_type": self.task_type,
            "description": self.description,
            "args_schema": public_args_schema,
            "semantic_inputs_schema": _plain(self.semantic_inputs_schema),
            "default_args": _plain(self.default_args),
            "output_schema": _plain(self.output_schema),
            "output_type": self.output_type,
            "upstream_input_bindings": _plain(self.upstream_input_bindings),
            "runtime_bound_args": sorted(runtime_bound),
            "selection_requirements": list(self.selection_requirements),
        }


@dataclass(frozen=True)
class AgentCapabilityCard:
    """Structured public contract for one MainAgent-selectable Worker.

    ``worker_id`` is the stable short identifier written into the Worker DAG.
    ``agent_id`` remains the existing runtime dispatch identifier so current
    Worker implementations and persisted traces stay compatible.
    """

    worker_id: str
    agent_id: str
    role: str
    description: str
    responsibility: str
    accepted_task_types: list[str] = field(default_factory=list)
    task_contracts: list[WorkerTaskContract] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    output_types: list[str] = field(default_factory=list)
    required_upstream_output_groups: list[list[str]] = field(default_factory=list)
    upstream_input_bindings: dict[str, dict[str, Any]] = field(default_factory=dict)
    authoritative_arg_bindings: dict[str, str] = field(default_factory=dict, repr=False)
    selection_requirements: list[str] = field(default_factory=list)
    dependency_arg_fields: dict[str, list[str]] = field(default_factory=dict, repr=False)
    non_responsibilities: list[str] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)
    missing_context_policy: str = "return_to_main_agent"
    supports_parallel: bool = True
    can_generate_proposal: bool = False
    private_tool_ids: list[str] = field(default_factory=list, repr=False)
    private_worker_prompt: str = field(default="", repr=False)

    def task_contract(self, task_type: str) -> WorkerTaskContract:
        wanted = str(task_type or "").strip()
        for contract in self.task_contracts:
            if contract.task_type == wanted:
                return contract
        if wanted not in self.accepted_task_types:
            raise KeyError(f"unknown_worker_task_contract:{self.worker_id}:{wanted}")
        return WorkerTaskContract(
            task_type=wanted,
            description=self.description,
            input_schema=self.input_schema,
            default_args={},
            output_schema=self.output_schema,
            output_type=(self.output_types[0] if len(self.output_types) == 1 else ""),
            upstream_input_bindings=self.upstream_input_bindings,
            authoritative_arg_bindings=self.authoritative_arg_bindings,
            selection_requirements=self.selection_requirements,
            private_tool_ids=self.private_tool_ids,
        )

    def authoritative_bindings_for(self, task_type: str) -> dict[str, str]:
        try:
            return dict(self.task_contract(task_type).authoritative_arg_bindings)
        except KeyError:
            return dict(self.authoritative_arg_bindings)

    def default_args_for(self, task_type: str) -> dict[str, Any]:
        try:
            return dict(self.task_contract(task_type).default_args)
        except KeyError:
            return {}

    def private_tools_for(self, task_type: str) -> list[str]:
        try:
            values = self.task_contract(task_type).private_tool_ids
        except KeyError:
            values = self.private_tool_ids
        return list(values or self.private_tool_ids)

    @property
    def input_description(self) -> str:
        """Compatibility summary retained for older callers and UI views."""

        required = list(self.input_schema.get("required") or [])
        return "required args: " + ", ".join(required) if required else "structured args object"

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    def safe_for_coordinator(self) -> dict[str, Any]:
        """Return the Worker card without private Tool or private prompt data."""

        public_input_schema = _plain(self.input_schema)
        if isinstance(public_input_schema, dict):
            runtime_bound = set(self.authoritative_arg_bindings)
            required = public_input_schema.get("required")
            if isinstance(required, list):
                public_input_schema["required"] = [
                    str(item) for item in required if str(item) not in runtime_bound
                ]
            public_input_schema["x-runtime-bound-args"] = sorted(runtime_bound)

        return {
            "worker_id": self.worker_id,
            "agent_id": self.agent_id,
            "role": self.role,
            "description": self.description,
            "responsibility": self.responsibility,
            "accepted_task_types": list(self.accepted_task_types),
            "task_contracts": [item.safe_for_coordinator() for item in self.task_contracts],
            "args_schema": public_input_schema,
            "semantic_inputs_schema": _plain(_semantic_inputs_schema(self.upstream_input_bindings)),
            "output_schema": _plain(self.output_schema),
            "output_types": list(self.output_types),
            "required_upstream_output_groups": _plain(self.required_upstream_output_groups),
            "upstream_input_bindings": _plain(self.upstream_input_bindings),
            "runtime_bound_args": sorted(self.authoritative_arg_bindings),
            "selection_requirements": list(self.selection_requirements),
            "non_responsibilities": list(self.non_responsibilities),
            "side_effects": list(self.side_effects),
            "missing_context_policy": self.missing_context_policy,
            "supports_parallel": self.supports_parallel,
            "can_generate_proposal": self.can_generate_proposal,
        }


@dataclass
class MissingContextItem:
    key: str
    description: str
    expected_format: str = ""
    reason: str = ""
    searched_sources: list[str] = field(default_factory=list)
    blocking: bool = True
    graph_refs: list[GraphRef] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.key = str(self.key or "").strip()
        self.description = str(self.description or self.key or "required context").strip()
        self.expected_format = str(self.expected_format or "").strip()
        self.reason = str(self.reason or "").strip()
        self.searched_sources = _str_list(self.searched_sources, limit=30)
        self.blocking = bool(self.blocking)
        self.graph_refs = refs_from(self.graph_refs)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MissingContextItem":
        return cls(**dict(value or {}))


@dataclass
class MemoryUpdate:
    key: str
    value: Any
    value_type: str = "json"
    source_type: str = "worker_result"
    source_ref: str = ""
    confirmed: bool = False
    confidence: float = 0.8
    summary: str = ""

    def __post_init__(self) -> None:
        self.key = str(self.key or "").strip()
        self.value_type = str(self.value_type or "json")
        self.source_type = str(self.source_type or "worker_result")
        self.source_ref = str(self.source_ref or "")
        self.confirmed = bool(self.confirmed)
        try:
            self.confidence = max(0.0, min(1.0, float(self.confidence)))
        except (TypeError, ValueError):
            self.confidence = 0.8
        self.summary = str(self.summary or "")[:1000]

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MemoryUpdate":
        return cls(**dict(value or {}))


@dataclass
class GraphAgentTask:
    task_id: str
    run_id: str
    session_id: str
    assigned_agent: str
    objective: str
    task_type: str
    user_id: str
    worker_id: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    expected_output_type: str = ""
    focus_refs: list[GraphRef] = field(default_factory=list)
    context_refs: list[GraphRef] = field(default_factory=list)
    dependency_task_ids: list[str] = field(default_factory=list)
    required_outputs: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    as_of_time: str = ""
    priority: int = 1
    status: TaskStatus = TaskStatus.CREATED
    attempt: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)
    contract_version: str = "graph_agent_task.v2"

    def __post_init__(self) -> None:
        self.task_id = str(self.task_id or new_id("task"))
        self.run_id = str(self.run_id or "")
        self.session_id = str(self.session_id or "")
        self.assigned_agent = str(self.assigned_agent or "").upper()
        self.objective = str(self.objective or "").strip()
        self.task_type = str(self.task_type or "general_analysis").strip()
        self.user_id = str(self.user_id or "default")
        self.worker_id = str(self.worker_id or "").strip().upper()
        self.args = dict(self.args or {})
        self.inputs = _task_inputs(self.inputs)
        self.expected_output_type = str(self.expected_output_type or "").strip()
        self.focus_refs = refs_from(self.focus_refs)
        self.context_refs = refs_from(self.context_refs)
        self.dependency_task_ids = _str_list(self.dependency_task_ids, limit=50)
        self.required_outputs = _str_list(self.required_outputs, limit=50)
        self.constraints = _str_list(self.constraints, limit=50)
        self.as_of_time = str(self.as_of_time or "")
        self.status = TaskStatus.from_value(self.status)
        self.metadata = dict(self.metadata or {})
        self.contract_version = "graph_agent_task.v2"
        try:
            self.priority = max(0, min(10, int(self.priority)))
        except (TypeError, ValueError):
            self.priority = 1
        try:
            self.attempt = max(1, int(self.attempt))
        except (TypeError, ValueError):
            self.attempt = 1

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    def input_task_ids(self, role: str | None = None) -> list[str]:
        """Return ordered task IDs declared by semantic upstream inputs."""

        selected = (
            {str(role): self.inputs.get(str(role), [])}
            if role is not None
            else self.inputs
        )
        result: list[str] = []
        for items in selected.values():
            for item in items:
                task_id = str(item.get("from_task_id") or "").strip()
                if task_id and task_id not in result:
                    result.append(task_id)
        return result

    def safe_for_coordinator(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "worker_id": self.worker_id,
            "assigned_agent": self.assigned_agent,
            "objective": self.objective,
            "task_type": self.task_type,
            "args": _compact(self.args, max_depth=4),
            "inputs": _compact(self.inputs, max_depth=4),
            "expected_output_type": self.expected_output_type,
            "user_id": self.user_id,
            "focus_refs": [ref.to_dict() for ref in self.focus_refs],
            "context_refs": [ref.to_dict() for ref in self.context_refs],
            "dependency_task_ids": list(self.dependency_task_ids),
            "required_outputs": list(self.required_outputs),
            "constraints": list(self.constraints),
            "as_of_time": self.as_of_time,
            "priority": self.priority,
            "status": self.status.value,
            "attempt": self.attempt,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GraphAgentTask":
        return cls(**dict(value or {}))


@dataclass
class GraphWorkerResult:
    task_id: str
    agent_id: str
    status: ResultStatus
    output_type: str = ""
    payload_schema: str = ""
    payload_version: str = "v1"
    payload: dict[str, Any] | None = None
    data: dict[str, Any] | None = field(default_factory=dict)
    error: dict[str, Any] | None = None
    focus_refs: list[GraphRef] = field(default_factory=list)
    summary: str = ""
    findings: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence_refs: list[GraphRef] = field(default_factory=list)
    graph_path_refs: list[GraphPathRef] = field(default_factory=list)
    graph_patch: GraphPatch | None = None
    graph_patch_ref: str = ""
    warnings: list[str] = field(default_factory=list)
    missing_items: list[MissingContextItem] = field(default_factory=list)
    memory_updates: list[MemoryUpdate] = field(default_factory=list)
    suggested_next_capabilities: list[str] = field(default_factory=list)
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    contract_version: str = "graph_worker_result.v1"

    def __post_init__(self) -> None:
        self.task_id = str(self.task_id or "")
        self.agent_id = str(self.agent_id or "").upper()
        self.status = ResultStatus.from_value(self.status)
        self.output_type = str(self.output_type or "").strip()
        self.payload_schema = str(self.payload_schema or (f"{self.output_type}.v1" if self.output_type else "")).strip()
        self.payload_version = str(self.payload_version or "v1").strip()
        if self.payload is None and self.data is not None:
            self.payload = dict(self.data or {})
        elif self.payload is not None:
            self.payload = dict(self.payload or {})
        if self.data is None and self.payload is not None:
            self.data = dict(self.payload)
        else:
            self.data = dict(self.data or {}) if self.data is not None else None
        self.error = dict(self.error or {}) if self.error is not None else None
        self.focus_refs = refs_from(self.focus_refs)
        self.summary = str(self.summary or "")[:8000]
        self.findings = _dict_list(self.findings, limit=100)
        self.recommendations = _str_list(self.recommendations, limit=50)
        try:
            self.confidence = max(0.0, min(1.0, float(self.confidence)))
        except (TypeError, ValueError):
            self.confidence = 0.0
        self.evidence_refs = refs_from(self.evidence_refs)
        self.graph_path_refs = [
            item if isinstance(item, GraphPathRef) else GraphPathRef(**item)
            for item in list(self.graph_path_refs or [])[:100]
        ]
        if self.graph_patch is not None and not isinstance(self.graph_patch, GraphPatch):
            self.graph_patch = GraphPatch.from_dict(dict(self.graph_patch))
        self.graph_patch_ref = str(self.graph_patch_ref or "")
        self.warnings = _str_list(self.warnings, limit=50)
        self.missing_items = [
            item if isinstance(item, MissingContextItem) else MissingContextItem.from_dict(item)
            for item in list(self.missing_items or [])[:50]
            if isinstance(item, (MissingContextItem, dict))
        ]
        self.memory_updates = [
            item if isinstance(item, MemoryUpdate) else MemoryUpdate.from_dict(item)
            for item in list(self.memory_updates or [])[:100]
            if isinstance(item, (MemoryUpdate, dict))
        ]
        self.suggested_next_capabilities = _str_list(self.suggested_next_capabilities, limit=30)
        self.artifact_refs = _dict_list(self.artifact_refs, limit=100)
        self.metadata = dict(self.metadata or {})
        self.contract_version = "graph_worker_result.v1"

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    def handoff_contract(self) -> dict[str, Any]:
        safe_metadata = {
            key: value
            for key, value in self.metadata.items()
            if key in {
                "task_type", "attempt", "partial_reason", "proposal_id", "plan_id",
                "requires_approval", "graph_view_id", "duration_ms",
                "tool_execution", "resolved_input_roles",
            }
        }
        return {
            "contract_version": self.contract_version,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "status": self.status.value,
            "output_type": self.output_type,
            "payload_schema": self.payload_schema,
            "payload_version": self.payload_version,
            "payload": _public_result_data(self.output_type, self.payload),
            "data": _public_result_data(self.output_type, self.data),
            "error": _compact(self.error, max_depth=3),
            "focus_refs": [ref.to_dict() for ref in self.focus_refs],
            "summary": self.summary[:1800],
            "findings": [_compact(item) for item in self.findings[:12]],
            "recommendations": list(self.recommendations[:12]),
            "confidence": self.confidence,
            "evidence_refs": [ref.to_dict() for ref in self.evidence_refs[:30]],
            "graph_path_refs": [path.to_dict() for path in self.graph_path_refs[:30]],
            "graph_patch_ref": self.graph_patch_ref,
            "warnings": list(self.warnings[:12]),
            "missing_items": [item.to_dict() for item in self.missing_items[:12]],
            "artifact_refs": [_compact(item, max_depth=3) for item in self.artifact_refs[:20]],
            "metadata": _compact(safe_metadata, max_depth=3),
        }

    def safe_for_coordinator(self) -> dict[str, Any]:
        return self.handoff_contract()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GraphWorkerResult":
        return cls(**dict(value or {}))


@dataclass
class SessionMemoryItem:
    memory_id: str
    session_id: str
    key: str
    value: Any
    value_type: str = "json"
    summary: str = ""
    source_type: str = ""
    source_ref: str = ""
    confirmed: bool = False
    confidence: float = 0.8
    version: int = 1
    status: str = "active"
    created_at: str = field(default_factory=now_text)
    updated_at: str = field(default_factory=now_text)
    expires_at: str = ""

    def __post_init__(self) -> None:
        self.memory_id = str(self.memory_id or new_id("smem"))
        self.session_id = str(self.session_id or "")
        self.key = str(self.key or "").strip()
        self.value_type = str(self.value_type or "json")
        self.summary = str(self.summary or "")[:1600]
        self.source_type = str(self.source_type or "")
        self.source_ref = str(self.source_ref or "")
        self.confirmed = bool(self.confirmed)
        try:
            self.confidence = max(0.0, min(1.0, float(self.confidence)))
        except (TypeError, ValueError):
            self.confidence = 0.8
        try:
            self.version = max(1, int(self.version))
        except (TypeError, ValueError):
            self.version = 1
        self.status = str(self.status or "active")
        self.created_at = str(self.created_at or now_text())
        self.updated_at = str(self.updated_at or self.created_at)
        self.expires_at = str(self.expires_at or "")

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)
