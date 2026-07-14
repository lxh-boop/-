from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.context.context_resolver import ContextResolver
from agent.context.context_sanitizer import ContextSanitizer
from agent.context.context_store import ContextStore
from agent.context.context_types import (
    ContextBundle,
    ConversationContext,
    MemoryContext,
    RuntimeContext,
    TaskContext,
    ToolContext,
    UserContext,
)
from agent.context.context_window import ContextWindow
from agent.memory.memory_context_bridge import build_memory_context_view


class ContextManager:
    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        output_dir: str | Path = "outputs",
        sanitizer: ContextSanitizer | None = None,
        store: ContextStore | None = None,
        resolver: ContextResolver | None = None,
        window: ContextWindow | None = None,
    ) -> None:
        self.db_path = db_path
        self.output_dir = output_dir
        self.sanitizer = sanitizer or ContextSanitizer()
        self.store = store or ContextStore(output_dir=output_dir, sanitizer=self.sanitizer)
        self.resolver = resolver or ContextResolver(
            db_path=db_path,
            output_dir=output_dir,
            sanitizer=self.sanitizer,
            store=self.store,
        )
        self.window = window or ContextWindow(self.sanitizer)

    def create_initial_context(
        self,
        *,
        user_id: str,
        query: str = "",
        conversation_id: str = "",
        run_id: str = "",
        task_id: str = "",
        locale: str = "zh-CN",
        user_profile_summary: dict[str, Any] | None = None,
        page_state: dict[str, Any] | None = None,
        user_goal: dict[str, Any] | None = None,
        task_plan: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ContextBundle:
        safe_page_state = self.sanitizer.sanitize_for_ui(page_state or {})
        memory_view = build_memory_context_view(
            user_id=str(user_id or "default"),
            query=str(query or ""),
            output_dir=self.output_dir,
            limit=6,
        )
        return ContextBundle(
            user_id=str(user_id or "default"),
            conversation_id=str(conversation_id or ""),
            run_id=str(run_id or ""),
            task_id=str(task_id or ""),
            locale=str(locale or "zh-CN"),
            user_context=UserContext(
                user_id=str(user_id or "default"),
                profile_summary=dict(user_profile_summary or {}),
            ),
            conversation_context=ConversationContext(
                conversation_id=str(conversation_id or ""),
                recent_messages=[{"role": "user", "content": str(query or "")}] if query else [],
            ),
            task_context=TaskContext(
                task_id=str(task_id or ""),
                user_goal=dict(user_goal or {"raw_message": str(query or "")}),
                task_plan=dict(task_plan or {}),
            ),
            runtime_context=RuntimeContext(
                run_id=str(run_id or ""),
                phase="initial",
                metadata={"page_state": safe_page_state} if safe_page_state else {},
            ),
            memory_context=MemoryContext(
                memory_refs=list(memory_view.get("memory_refs") or []),
                user_preference_refs=[
                    str((item.get("memory") or {}).get("memory_id") or "")
                    for item in (memory_view.get("items") or [])
                    if str((item.get("memory") or {}).get("memory_subtype") or "").lower() in {"preference", "risk_preference"}
                ],
                recent_decision_refs=[],
                metadata={
                    "phase14_memory": {
                        "item_count": int(memory_view.get("item_count") or 0),
                        "policy": dict(memory_view.get("policy") or {}),
                    }
                },
            ),
            metadata=dict(metadata or {}),
        )

    def update_from_tool_result(
        self,
        bundle: ContextBundle,
        tool_result: dict[str, Any] | Any,
    ) -> ContextBundle:
        result = tool_result.to_dict() if hasattr(tool_result, "to_dict") else dict(tool_result or {})
        safe_result = self.sanitizer.sanitize_for_audit(result)
        visible_result_keys = [
            str(key)
            for key in safe_result.keys()
            if self.sanitizer.policy.visibility_for(str(key)).value != "secret"
        ]
        bundle.tool_context = ToolContext(
            allowed_tools=list(bundle.tool_context.allowed_tools or []),
            current_tool=str(result.get("tool_name") or bundle.tool_context.current_tool or ""),
            arguments=dict(bundle.tool_context.arguments or {}),
            result_summary={
                "success": bool(result.get("success")),
                "tool_name": result.get("tool_name"),
                "message": str(result.get("message") or "")[:300],
                "artifact_id": result.get("artifact_id") or "",
            },
            full_result_ref=str(result.get("artifact_id") or bundle.tool_context.full_result_ref or ""),
            metadata={
                "result_keys": sorted(visible_result_keys),
                "has_artifact_ref": bool(
                    isinstance(result.get("metadata"), dict)
                    and isinstance((result.get("metadata") or {}).get("artifact_ref"), dict)
                ),
            },
        )
        artifact_ref = (result.get("metadata") or {}).get("artifact_ref") if isinstance(result.get("metadata"), dict) else {}
        if artifact_ref and isinstance(artifact_ref, dict):
            existing = list(bundle.artifact_context.artifact_refs or [])
            safe_ref = ContextStore._safe_artifact_ref(artifact_ref)
            if safe_ref and safe_ref not in existing:
                existing.append(safe_ref)
            bundle.artifact_context.artifact_refs = existing
            if safe_ref.get("artifact_id") and safe_ref["artifact_id"] not in bundle.artifact_context.readable_artifact_ids:
                bundle.artifact_context.readable_artifact_ids.append(safe_ref["artifact_id"])
        return bundle

    def build_approval_context(self, *, user_id: str, plan_id: str):
        return self.resolver.approval_context_from_plan(user_id=user_id, plan_id=plan_id)

    def build_artifact_context(
        self,
        *,
        user_id: str,
        refs: list[dict[str, Any]],
        conversation_id: str = "",
        run_id: str = "",
    ):
        return self.resolver.artifact_context_from_refs(
            refs,
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run_id,
        )

    def build_llm_context(self, bundle: ContextBundle, *, max_tokens: int | None = None) -> dict[str, Any]:
        return self.window.trim_to_budget(bundle, target="llm", max_tokens=max_tokens)

    def build_tool_context(self, bundle: ContextBundle, *, permission_scope: str = "read") -> dict[str, Any]:
        return self.sanitizer.sanitize_for_tool(bundle, permission_scope=permission_scope)

    def save_snapshot(self, bundle: ContextBundle) -> dict[str, Any]:
        return self.store.save_context_snapshot(bundle)


__all__ = ["ContextManager"]
