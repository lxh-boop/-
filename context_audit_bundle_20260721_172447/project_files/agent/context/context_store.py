from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.context.context_sanitizer import ContextSanitizer
from agent.context.context_types import ContextBundle
from runtime_paths import get_runtime_dir


class ContextStore:
    def __init__(
        self,
        *,
        output_dir: str | Path | None = None,
        sanitizer: ContextSanitizer | None = None,
    ) -> None:
        self.output_dir = Path(output_dir) if output_dir else get_runtime_dir()
        self.sanitizer = sanitizer or ContextSanitizer()

    def _root(self, user_id: str) -> Path:
        root = self.output_dir / "context_snapshots" / str(user_id or "default")
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _path(self, user_id: str, context_id: str) -> Path:
        return self._root(user_id) / f"{context_id}.json"

    def save_context_snapshot(self, bundle: ContextBundle | dict[str, Any]) -> dict[str, Any]:
        payload = bundle.to_dict() if hasattr(bundle, "to_dict") else dict(bundle or {})
        payload = self.sanitizer.sanitize_for_audit(payload)
        context_id = str(payload.get("context_id") or "")
        if not context_id:
            raise ValueError("context_id_required")
        user_id = str(payload.get("user_id") or "default")
        path = self._path(user_id, context_id)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
        return {
            "context_id": context_id,
            "user_id": user_id,
            "path": str(path),
            "status": payload.get("metadata", {}).get("status", "active") if isinstance(payload.get("metadata"), dict) else "active",
        }

    def load_context_snapshot(self, *, user_id: str, context_id: str) -> dict[str, Any] | None:
        path = self._path(user_id, context_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def append_tool_result(
        self,
        *,
        user_id: str,
        context_id: str,
        tool_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        snapshot = self.load_context_snapshot(user_id=user_id, context_id=context_id)
        if not snapshot:
            return None
        tool_context = snapshot.setdefault("tool_context", {})
        history = tool_context.setdefault("result_history", [])
        safe_result = self.sanitizer.sanitize_for_audit(dict(tool_result or {}))
        history.append(safe_result)
        tool_context["result_summary"] = {
            "tool_name": safe_result.get("tool_name"),
            "success": safe_result.get("success"),
            "message": str(safe_result.get("message") or "")[:300],
            "artifact_id": safe_result.get("artifact_id") or (safe_result.get("metadata") or {}).get("artifact_id"),
        }
        self.save_context_snapshot(snapshot)
        return snapshot

    def append_artifact_ref(
        self,
        *,
        user_id: str,
        context_id: str,
        artifact_ref: dict[str, Any],
    ) -> dict[str, Any] | None:
        snapshot = self.load_context_snapshot(user_id=user_id, context_id=context_id)
        if not snapshot:
            return None
        artifact_context = snapshot.setdefault("artifact_context", {})
        refs = artifact_context.setdefault("artifact_refs", [])
        safe_ref = self._safe_artifact_ref(artifact_ref)
        if safe_ref and safe_ref not in refs:
            refs.append(safe_ref)
        if safe_ref.get("artifact_id"):
            ids = artifact_context.setdefault("readable_artifact_ids", [])
            if safe_ref["artifact_id"] not in ids:
                ids.append(safe_ref["artifact_id"])
        self.save_context_snapshot(snapshot)
        return snapshot

    def append_runtime_event(
        self,
        *,
        user_id: str,
        context_id: str,
        event: dict[str, Any],
    ) -> dict[str, Any] | None:
        snapshot = self.load_context_snapshot(user_id=user_id, context_id=context_id)
        if not snapshot:
            return None
        runtime_context = snapshot.setdefault("runtime_context", {})
        events = runtime_context.setdefault("events", [])
        events.append(self.sanitizer.sanitize_for_audit(dict(event or {})))
        self.save_context_snapshot(snapshot)
        return snapshot

    def expire_context(self, *, user_id: str, context_id: str, reason: str = "") -> dict[str, Any] | None:
        snapshot = self.load_context_snapshot(user_id=user_id, context_id=context_id)
        if not snapshot:
            return None
        metadata = snapshot.setdefault("metadata", {})
        metadata["status"] = "expired"
        metadata["expire_reason"] = str(reason or "")
        self.save_context_snapshot(snapshot)
        return snapshot

    @staticmethod
    def _safe_artifact_ref(artifact_ref: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in dict(artifact_ref or {}).items()
            if key in {"artifact_id", "artifact_type", "content_hash", "produced_outputs", "created_at", "expires_at", "status"}
            and value not in ("", None)
        }
