from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


AGENT_OUTPUT_FIELDS = (
    "evidence",
    "analysis",
    "proposal",
    "risks",
    "next_actions",
    "sources",
)


def make_message_id(role: str) -> str:
    prefix = str(role or "agent").strip().lower().replace(" ", "_")
    return f"msg_{prefix}_{uuid4().hex[:12]}"


def compact_preview(value: Any, max_chars: int = 360) -> str:
    text = str(value if value is not None else "")
    return text if len(text) <= max_chars else text[:max_chars] + "...[truncated]"


@dataclass(frozen=True)
class AgentMessage:
    message_id: str
    sender: str
    receiver: str
    payload: dict[str, Any] = field(default_factory=dict)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentOutput:
    role: str
    message_id: str
    status: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    analysis: dict[str, Any] = field(default_factory=dict)
    proposal: dict[str, Any] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    handoff_from: str = ""
    handoff_to: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def output_summary(output: AgentOutput | dict[str, Any]) -> dict[str, Any]:
    data = output.to_dict() if hasattr(output, "to_dict") else dict(output or {})
    return {
        "role": data.get("role", ""),
        "status": data.get("status", ""),
        "evidence_count": len(data.get("evidence") or []),
        "analysis_keys": sorted((data.get("analysis") or {}).keys()),
        "proposal_keys": sorted((data.get("proposal") or {}).keys()),
        "risk_count": len(data.get("risks") or []),
        "next_action_count": len(data.get("next_actions") or []),
        "source_count": len(data.get("sources") or []),
        "tool_call_count": len(data.get("tool_calls") or []),
    }


def timeline_entry(
    *,
    step_id: str,
    role: str,
    status: str,
    message_id: str,
    input_summary: Any,
    output_summary_text: Any,
    handoff_from: str = "",
    handoff_to: str = "",
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "role": role,
        "status": status,
        "message_id": message_id,
        "handoff_from": handoff_from,
        "handoff_to": handoff_to,
        "depends_on": list(depends_on or []),
        "input_summary": compact_preview(input_summary),
        "output_summary": compact_preview(output_summary_text),
    }
