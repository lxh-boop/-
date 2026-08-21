"""Rule-driven context hydration before authoritative entity resolution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agent.memory.memory_context_bridge import build_memory_context_view
from agent.graph.contracts import GraphRef, refs_from


@dataclass(frozen=True)
class ContextRequirement:
    context_key: str
    required: bool = True
    source_preferences: list[str] = field(default_factory=list)
    entity_role: str = ""
    freshness_policy: str = "request_default"
    authority_policy: str = "verified"
    allow_session_inheritance: bool = False


@dataclass(frozen=True)
class HydratedContext:
    user_id: str
    session_id: str
    session_summary: str
    previous_focus_refs: list[GraphRef]
    typed_focus_refs: dict[str, list[GraphRef]]
    pending_run_ids: list[str]
    pending_proposal_ids: list[str]
    permission_context: dict[str, Any]
    available_parameters: dict[str, Any]
    long_term_memory_summary: str
    long_term_memory_refs: list[str]
    source_audit: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["previous_focus_refs"] = [item.to_dict() for item in self.previous_focus_refs]
        result["typed_focus_refs"] = {
            key: [item.to_dict() for item in refs]
            for key, refs in self.typed_focus_refs.items()
        }
        return result


class ContextHydrator:
    """Read only the context requested by the lightweight interpreter."""

    def __init__(
        self,
        *,
        session_state: Any,
        checkpoint_store: Any = None,
        output_dir: str = "outputs",
    ) -> None:
        self.session_state = session_state
        self.checkpoint_store = checkpoint_store
        self.output_dir = output_dir

    def hydrate(
        self,
        *,
        user_id: str,
        session_id: str,
        requirements: list[ContextRequirement] | None,
        query: str = "",
        run_id: str = "",
        execution_context: dict[str, Any] | None = None,
    ) -> HydratedContext:
        context = dict(execution_context or {})
        required_ids = {item.context_key for item in requirements or []}
        previous_refs: list[GraphRef] = []
        summary = ""
        audit: list[dict[str, Any]] = []
        focus_requirement = next(
            (item for item in requirements or [] if item.context_key == "previous_focus_entities"),
            None,
        )
        if focus_requirement is not None and focus_requirement.allow_session_inheritance:
            try:
                item = self.session_state.get(session_id, "active_graph_refs")
                if item is not None:
                    previous_refs = refs_from(item.value)
                    audit.append({"context_key": "previous_focus_entities", "source": "session_state"})
            except Exception:
                previous_refs = []
        typed_focus_refs: dict[str, list[GraphRef]] = {}
        typed_requirements = [
            item for item in requirements or []
            if str(item.context_key or "").startswith("typed_focus:")
            and item.allow_session_inheritance
        ]
        for requirement in typed_requirements:
            focus_type = str(requirement.context_key).split(":", 1)[1].strip().lower()
            if not focus_type:
                continue
            try:
                item = self.session_state.get(session_id, f"typed_graph_focus:{focus_type}")
                if item is not None:
                    refs = refs_from(item.value)
                    if refs:
                        typed_focus_refs[focus_type] = refs
                        audit.append({
                            "context_key": f"typed_focus:{focus_type}",
                            "source": "session_state",
                            "record_count": len(refs),
                        })
            except Exception:
                typed_focus_refs[focus_type] = []
        if not required_ids or "session_summary" in required_ids:
            try:
                rows = self.session_state.list_latest(session_id, limit=20)
                summaries = [str(item.summary) for item in rows if str(item.summary).strip()]
                summary = "\n".join(summaries[-8:])[:2400]
                if summary:
                    audit.append({"context_key": "session_summary", "source": "session_state"})
            except Exception:
                summary = ""
        pending_runs: list[str] = []
        if self.checkpoint_store is not None:
            try:
                pending_runs = [item.run_id for item in self.checkpoint_store.pending_for_session(session_id)]
                if pending_runs:
                    audit.append({"context_key": "pending_runs", "source": "run_checkpoint_store"})
            except Exception:
                pending_runs = []
        long_term_summary = ""
        long_term_refs: list[str] = []
        if not required_ids or "long_term_memory" in required_ids:
            try:
                view = build_memory_context_view(
                    user_id=str(user_id or "default"),
                    query=str(query or ""),
                    output_dir=self.output_dir,
                    conversation_id=str(session_id or ""),
                    run_id=str(run_id or ""),
                    agent_role="main_agent",
                    token_budget=420,
                    relevance_threshold=0.42,
                )
                long_term_refs = [str(item) for item in view.get("memory_refs") or [] if str(item)]
                rows = []
                for item in view.get("items") or []:
                    memory = item.get("memory") if isinstance(item, dict) else {}
                    if isinstance(memory, dict):
                        text = str(memory.get("summary") or memory.get("content") or "").strip()
                        if text:
                            rows.append(text)
                long_term_summary = "\n".join(rows)[:2400]
                if long_term_refs:
                    audit.append({
                        "context_key": "long_term_memory",
                        "source": "sqlite_memory_store",
                        "record_count": len(long_term_refs),
                    })
            except Exception as exc:
                audit.append({
                    "context_key": "long_term_memory",
                    "source": "sqlite_memory_store",
                    "status": "unavailable",
                    "error": type(exc).__name__,
                })
        pending_proposals = [
            str(item) for item in context.get("pending_proposal_ids") or [] if str(item)
        ]
        parameters = dict(context.get("available_parameters") or {})
        for key in ("top_k", "model_name", "trade_date", "holding_period", "as_of_time"):
            if key in context and context[key] not in (None, ""):
                parameters[key] = context[key]
        return HydratedContext(
            user_id=str(user_id or "default"),
            session_id=str(session_id or ""),
            session_summary=summary,
            previous_focus_refs=previous_refs,
            typed_focus_refs=typed_focus_refs,
            pending_run_ids=pending_runs,
            pending_proposal_ids=pending_proposals,
            permission_context=dict(context.get("permission_context") or {}),
            available_parameters=parameters,
            long_term_memory_summary=long_term_summary,
            long_term_memory_refs=long_term_refs,
            source_audit=audit,
        )
