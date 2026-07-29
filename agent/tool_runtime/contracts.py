"""Stable data contracts and authorization constants for registered tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable


OP_READ = "read"
OP_PROPOSAL = "proposal"
OP_WRITE = "write"
OP_SYSTEM = "system"

AGENT_MAIN = "main_agent"
AGENT_READ = "read_worker"
AGENT_WRITE = "write_worker"
AGENT_WORKER = "worker_agent"

TOOL_RESULT_SCHEMA_VERSION = "tool-result-v1"

TOOL_VISIBILITY_PUBLIC = "public"
TOOL_VISIBILITY_WORKER_PRIVATE = "worker_private"
TOOL_VISIBILITY_SYSTEM_PRIVATE = "system_private"
TOOL_VISIBILITIES = frozenset(
    {
        TOOL_VISIBILITY_PUBLIC,
        TOOL_VISIBILITY_WORKER_PRIVATE,
        TOOL_VISIBILITY_SYSTEM_PRIVATE,
    }
)


@dataclass(frozen=True)
class UnifiedToolResult:
    """Normalized result returned by every registered tool execution."""

    success: bool
    tool_name: str
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    error_type: str = ""
    error_message: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    artifact_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0
    retry_count: int = 0
    circuit_state: str = ""
    schema_version: str = TOOL_RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_legacy_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "data": dict(self.data or {}),
            "warnings": list(self.warnings or []),
            "errors": list(self.errors or []),
            "tool_name": self.tool_name,
            "runtime_reliability": dict(self.metadata.get("runtime_reliability") or {}),
            "artifact_id": self.artifact_id,
            "tool_engine": {
                "schema_version": self.schema_version,
                "canonical_tool_name": self.metadata.get("canonical_tool_name"),
                "duration_ms": self.duration_ms,
                "retry_count": self.retry_count,
                "circuit_state": self.circuit_state,
            },
        }


@dataclass(frozen=True)
class ToolDefinition:
    """Declarative contract for one atomic domain capability."""

    name: str
    display_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    execution_handler: Callable[[dict[str, Any], dict[str, Any]], Any]
    argument_builder: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    supported_actions: list[str] = field(default_factory=list)
    supported_objects: list[str] = field(default_factory=list)
    produced_outputs: list[str] = field(default_factory=list)
    required_dependency_outputs: list[str] = field(default_factory=list)
    operation_type: str = OP_READ
    allowed_agent_types: list[str] = field(default_factory=lambda: [AGENT_MAIN, AGENT_READ])
    allowed_capability_ids: list[str] = field(default_factory=list)
    permission_scope: str = OP_READ
    requires_approval: bool = False
    runtime_policy: dict[str, Any] = field(default_factory=dict)
    version: str = "1"
    enabled: bool = True
    sensitivity: str = "normal"
    tags: list[str] = field(default_factory=list)
    legacy_names: list[str] = field(default_factory=list)
    visibility: str = TOOL_VISIBILITY_PUBLIC
    side_effects: list[str] = field(default_factory=list)
    mutates_business_state: bool = False
    idempotency: str = "unspecified"
    audit_level: str = "standard"

    def public_view(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("execution_handler", None)
        data.pop("argument_builder", None)
        return data
