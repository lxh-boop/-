from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from agent.artifacts import ArtifactStore
from agent.context.context_sanitizer import ContextSanitizer
from agent.context.context_store import ContextStore
from agent.context.context_types import ApprovalContext, ArtifactContext, EvidenceContext, PortfolioContext
from agent.session.pending_action_store import get_pending_plan


class ContextResolver:
    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        output_dir: str | Path = "outputs",
        sanitizer: ContextSanitizer | None = None,
        store: ContextStore | None = None,
    ) -> None:
        self.db_path = db_path
        self.output_dir = output_dir
        self.sanitizer = sanitizer or ContextSanitizer()
        self.store = store or ContextStore(output_dir=output_dir, sanitizer=self.sanitizer)

    def resolve_artifact_ref(
        self,
        artifact_ref: str | dict[str, Any],
        *,
        user_id: str,
        conversation_id: str = "",
        run_id: str = "",
    ) -> dict[str, Any]:
        artifact_id = artifact_ref.get("artifact_id") if isinstance(artifact_ref, dict) else artifact_ref
        artifact_id = str(artifact_id or "")
        if not artifact_id:
            return {"resolved": False, "error": "artifact_id_required"}
        payload = ArtifactStore(db_path=self.db_path, output_dir=self.output_dir).read(
            artifact_id,
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run_id,
        )
        if not payload:
            return {"resolved": False, "artifact_id": artifact_id, "error": "artifact_not_found_or_not_readable"}
        expires_at = str(payload.get("expires_at") or "")
        expired = False
        if expires_at:
            try:
                expired = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S") < datetime.now()
            except ValueError:
                expired = False
        return {
            "resolved": True,
            "artifact_id": artifact_id,
            "artifact_type": payload.get("artifact_type"),
            "schema_version": payload.get("schema_version"),
            "producer_type": payload.get("producer_type"),
            "producer_id": payload.get("producer_id"),
            "content_summary": self.sanitizer.sanitize_for_llm(payload.get("content_summary") or {}),
            "produced_outputs": payload.get("content", {}).get("produced_outputs") or [],
            "sources": self.sanitizer.sanitize_for_llm({"sources": payload.get("sources") or []}).get("sources", []),
            "created_at": payload.get("created_at"),
            "expires_at": expires_at,
            "expired": expired,
            "lineage": {
                "conversation_id": payload.get("conversation_id") or "",
                "run_id": payload.get("run_id") or "",
                "task_id": payload.get("task_id") or "",
            },
        }

    def resolve_previous_tool_result(
        self,
        *,
        user_id: str,
        context_id: str = "",
        artifact_id: str = "",
        conversation_id: str = "",
        run_id: str = "",
    ) -> dict[str, Any]:
        if artifact_id:
            resolved = self.resolve_artifact_ref(
                artifact_id,
                user_id=user_id,
                conversation_id=conversation_id,
                run_id=run_id,
            )
            return {
                "resolved": bool(resolved.get("resolved")),
                "source": "artifact",
                "tool_result_summary": resolved.get("content_summary") or {},
                "artifact": resolved,
            }
        if context_id:
            snapshot = self.store.load_context_snapshot(user_id=user_id, context_id=context_id)
            if snapshot:
                tool_context = snapshot.get("tool_context") if isinstance(snapshot.get("tool_context"), dict) else {}
                return {
                    "resolved": True,
                    "source": "context_snapshot",
                    "tool_result_summary": tool_context.get("result_summary") or {},
                    "result_history_count": len(tool_context.get("result_history") or []),
                }
        return {"resolved": False, "error": "previous_tool_result_not_found"}

    def resolve_pending_plan(
        self,
        *,
        user_id: str,
        plan_id: str,
    ) -> dict[str, Any]:
        plan = get_pending_plan(user_id, plan_id, self.output_dir)
        if not plan:
            return {"resolved": False, "error": "pending_plan_not_found", "plan_id": str(plan_id or "")}
        safe_summary = {
            "plan_id": str(plan.get("plan_id") or ""),
            "intent": str(plan.get("intent") or ""),
            "operation_type": str(plan.get("operation_type") or plan.get("intent") or ""),
            "status": str(plan.get("confirmation_status") or ""),
            "execution_status": str(plan.get("execution_status") or ""),
            "plan_hash": str(plan.get("plan_hash") or ""),
            "expires_at": str(plan.get("expires_at") or ""),
            "revalidate_required": True,
            "confirmation_token_status": "present" if plan.get("confirmation_token") else "missing",
            "requires_confirmation": bool(plan.get("requires_confirmation", True)),
            "summary": {
                "before_state_summary": plan.get("before_state_summary") or plan.get("before") or {},
                "proposed_changes": plan.get("proposed_changes") or [],
                "after_state_preview": plan.get("after_state_preview") or plan.get("after") or {},
                "warnings": plan.get("warnings") or [],
                "validation_results": plan.get("validation_results") or {},
            },
        }
        safe_summary = self.sanitizer.sanitize_for_llm(safe_summary)
        return {"resolved": True, **safe_summary}

    def resolve_current_portfolio_ref(self, *, user_id: str) -> dict[str, Any]:
        return {
            "resolved": True,
            "portfolio_ref": {
                "user_id": str(user_id or "default"),
                "ref_type": "current_portfolio_state",
                "summary_available": True,
            },
        }

    def resolve_evidence_refs(self, refs: list[str] | None = None) -> dict[str, Any]:
        refs = [str(ref) for ref in (refs or []) if str(ref).strip()]
        return {"resolved": bool(refs), "source_refs": refs[:50], "truncated_count": max(0, len(refs) - 50)}

    def resolve_user_preference_ref(self, *, user_id: str, refs: list[str] | None = None) -> dict[str, Any]:
        return {
            "resolved": bool(refs),
            "user_id": str(user_id or "default"),
            "user_preference_refs": [str(ref) for ref in (refs or []) if str(ref).strip()][:20],
        }

    def artifact_context_from_refs(
        self,
        refs: list[dict[str, Any]] | None,
        *,
        user_id: str,
        conversation_id: str = "",
        run_id: str = "",
    ) -> ArtifactContext:
        safe_refs: list[dict[str, Any]] = []
        produced_outputs: list[str] = []
        readable_ids: list[str] = []
        for ref in refs or []:
            resolved = self.resolve_artifact_ref(ref, user_id=user_id, conversation_id=conversation_id, run_id=run_id)
            if not resolved.get("resolved"):
                continue
            safe_refs.append(
                {
                    "artifact_id": resolved.get("artifact_id"),
                    "artifact_type": resolved.get("artifact_type"),
                    "producer_id": resolved.get("producer_id"),
                    "produced_outputs": resolved.get("produced_outputs") or [],
                    "expired": bool(resolved.get("expired")),
                }
            )
            readable_ids.append(str(resolved.get("artifact_id") or ""))
            for output in resolved.get("produced_outputs") or []:
                if output not in produced_outputs:
                    produced_outputs.append(str(output))
        return ArtifactContext(
            artifact_refs=safe_refs,
            produced_outputs=produced_outputs,
            readable_artifact_ids=[item for item in readable_ids if item],
        )

    def approval_context_from_plan(self, *, user_id: str, plan_id: str) -> ApprovalContext:
        resolved = self.resolve_pending_plan(user_id=user_id, plan_id=plan_id)
        if not resolved.get("resolved"):
            return ApprovalContext(pending_plan_id=str(plan_id or ""), status="not_found", token_present=False)
        return ApprovalContext(
            pending_plan_id=str(resolved.get("plan_id") or ""),
            plan_hash=str(resolved.get("plan_hash") or ""),
            status=str(resolved.get("status") or ""),
            token_present=resolved.get("confirmation_token_status") == "present",
            pending_plan_summary={
                "intent": resolved.get("intent"),
                "operation_type": resolved.get("operation_type"),
                "expires_at": resolved.get("expires_at"),
                "revalidate_required": resolved.get("revalidate_required"),
                "requires_confirmation": resolved.get("requires_confirmation"),
                "summary": resolved.get("summary") or {},
            },
        )


__all__ = [
    "ApprovalContext",
    "ArtifactContext",
    "ContextResolver",
    "EvidenceContext",
    "PortfolioContext",
]
