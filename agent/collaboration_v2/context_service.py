from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .models import AgentTask
from .session_memory import SessionMemoryStore


ArtifactLoader = Callable[[str], dict[str, Any] | None]


@dataclass
class ContextReadResult:
    found: bool
    source: str
    key: str = ""
    value: Any = None
    summary: str = ""
    ref: str = ""
    warnings: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": bool(self.found),
            "source": str(self.source or ""),
            "key": str(self.key or ""),
            "value": self.value,
            "summary": str(self.summary or ""),
            "ref": str(self.ref or ""),
            "warnings": list(self.warnings or []),
        }


class ContextService:
    """Specialist-only access to session memory and dependency references."""

    def __init__(
        self,
        memory: SessionMemoryStore,
        *,
        dependency_results: dict[str, dict[str, Any]] | None = None,
        artifact_loader: ArtifactLoader | None = None,
    ) -> None:
        self.memory = memory
        self.dependency_results = dict(dependency_results or {})
        self.artifact_loader = artifact_loader

    def memory_get(
        self,
        *,
        session_id: str,
        key: str,
        run_id: str = "",
        task_id: str = "",
        agent_id: str = "",
    ) -> dict[str, Any]:
        item = self.memory.get(session_id, key)
        self.memory.log_access(
            session_id=session_id,
            run_id=run_id,
            task_id=task_id,
            agent_id=agent_id,
            operation="get",
            query_text=key,
            matched_keys=[item.key] if item else [],
        )
        if not item:
            return ContextReadResult(found=False, source="session_memory", key=key).to_dict()
        return ContextReadResult(
            found=True,
            source="session_memory",
            key=item.key,
            value=item.value,
            summary=item.summary,
            ref=f"memory:{item.key}",
        ).to_dict()

    def memory_search(
        self,
        *,
        session_id: str,
        query: str,
        limit: int = 8,
        run_id: str = "",
        task_id: str = "",
        agent_id: str = "",
    ) -> dict[str, Any]:
        items = self.memory.search(
            session_id,
            query,
            limit=limit,
            run_id=run_id,
            task_id=task_id,
            agent_id=agent_id,
        )
        return {
            "found": bool(items),
            "source": "session_memory",
            "query": str(query or ""),
            "matches": [
                {
                    "key": item.key,
                    "value": item.value,
                    "summary": item.summary,
                    "confirmed": item.confirmed,
                    "confidence": item.confidence,
                    "version": item.version,
                    "ref": f"memory:{item.key}",
                }
                for item in items
            ],
        }

    def read_context_ref(
        self,
        ref: str,
        *,
        session_id: str,
        run_id: str = "",
        task_id: str = "",
        agent_id: str = "",
    ) -> dict[str, Any]:
        reference = str(ref or "").strip()
        if not reference:
            return ContextReadResult(found=False, source="reference", warnings=["empty_reference"]).to_dict()
        if reference.startswith("memory:"):
            return self.memory_get(
                session_id=session_id,
                key=reference.split(":", 1)[1],
                run_id=run_id,
                task_id=task_id,
                agent_id=agent_id,
            )
        if reference.startswith("result:"):
            result_id = reference.split(":", 1)[1]
            result = self.dependency_results.get(result_id)
            return ContextReadResult(
                found=isinstance(result, dict),
                source="dependency_result",
                key=result_id,
                value=result if isinstance(result, dict) else None,
                summary=str((result or {}).get("summary") or "") if isinstance(result, dict) else "",
                ref=reference,
            ).to_dict()
        if reference.startswith("artifact:"):
            if self.artifact_loader is None:
                return ContextReadResult(
                    found=False,
                    source="artifact",
                    ref=reference,
                    warnings=["artifact_loader_not_configured"],
                ).to_dict()
            try:
                value = self.artifact_loader(reference)
            except Exception as exc:  # Runtime boundary: never expose stack/path details.
                return ContextReadResult(
                    found=False,
                    source="artifact",
                    ref=reference,
                    warnings=[f"artifact_read_failed:{type(exc).__name__}"],
                ).to_dict()
            return ContextReadResult(
                found=isinstance(value, dict),
                source="artifact",
                value=value if isinstance(value, dict) else None,
                summary=str((value or {}).get("summary") or "") if isinstance(value, dict) else "",
                ref=reference,
            ).to_dict()
        return ContextReadResult(
            found=False,
            source="reference",
            ref=reference,
            warnings=["unsupported_reference_scheme"],
        ).to_dict()

    def build_auto_context(
        self,
        task: AgentTask,
        *,
        current_user_request: str,
        dependency_results: dict[str, dict[str, Any]],
        max_summary_chars: int = 3000,
    ) -> dict[str, Any]:
        summary = self.memory.build_summary(
            task.session_id,
            task_objective=task.objective,
            max_chars=max_summary_chars,
        )
        dependencies = {
            task_id: {
                "contract_version": str(result.get("contract_version") or "standardized_agent_result.v1"),
                "agent_id": str(result.get("agent_id") or ""),
                "status": str(result.get("status") or ""),
                "summary": str(result.get("summary") or "")[:1200],
                "findings": list(result.get("findings") or [])[:8],
                "recommendations": list(result.get("recommendations") or [])[:8],
                "evidence_refs": list(result.get("evidence_refs") or [])[:12],
                "artifact_refs": list(result.get("artifact_refs") or [])[:12],
                "missing_items": list(result.get("missing_items") or [])[:8],
                "metadata": dict(result.get("metadata") or {}),
            }
            for task_id, result in dependency_results.items()
            if task_id in task.dependency_task_ids and isinstance(result, dict)
        }
        return {
            "current_user_request": str(current_user_request or "")[:3000],
            "task": task.safe_for_coordinator(),
            "session_memory_summary": summary,
            "dependency_results": dependencies,
            "context_tools": ["memory_get", "memory_search", "read_context_ref"],
            "context_rule": (
                "Use the injected summary first. Read detailed session memory or references only when needed. "
                "Do not invent critical facts."
            ),
        }
