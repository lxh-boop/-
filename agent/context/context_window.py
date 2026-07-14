from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from agent.context.context_sanitizer import ContextSanitizer
from agent.context.context_types import ContextBundle
from agent.context.schemas import estimate_tokens


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


class ContextWindow:
    def __init__(self, sanitizer: ContextSanitizer | None = None, *, default_budget: int = 1800) -> None:
        self.sanitizer = sanitizer or ContextSanitizer()
        self.default_budget = int(default_budget or 1800)

    def estimate_context_size(self, value: Any) -> int:
        return estimate_tokens(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))

    def keep_required_refs(self, value: dict[str, Any]) -> dict[str, Any]:
        data = deepcopy(value)
        task = data.setdefault("task_context", {})
        artifact = data.setdefault("artifact_context", {})
        approval = data.setdefault("approval_context", {})
        kept_refs: list[str] = []

        for ref in task.get("required_refs") or []:
            if ref not in kept_refs:
                kept_refs.append(str(ref))
        for ref in artifact.get("readable_artifact_ids") or []:
            if ref not in kept_refs:
                kept_refs.append(str(ref))
        for item in artifact.get("artifact_refs") or []:
            if isinstance(item, dict) and item.get("artifact_id") and item.get("artifact_id") not in kept_refs:
                kept_refs.append(str(item.get("artifact_id")))
        if approval.get("pending_plan_id") and approval.get("pending_plan_id") not in kept_refs:
            kept_refs.append(str(approval.get("pending_plan_id")))
        data.setdefault("metadata", {})["required_refs_kept"] = kept_refs
        return data

    def summarize_old_context(self, value: dict[str, Any], *, max_messages: int = 4) -> dict[str, Any]:
        data = deepcopy(value)
        conversation = data.get("conversation_context")
        if isinstance(conversation, dict):
            messages = conversation.get("recent_messages")
            if isinstance(messages, list) and len(messages) > max_messages:
                conversation["recent_messages"] = messages[-max_messages:]
                conversation["dropped_message_count"] = len(messages) - max_messages
            for message in conversation.get("recent_messages") or []:
                if isinstance(message, dict) and isinstance(message.get("content"), str) and len(message["content"]) > 600:
                    message["content"] = message["content"][:600] + "...[truncated]"
        return data

    def trim_to_budget(
        self,
        bundle: ContextBundle | dict[str, Any],
        *,
        target: str = "llm",
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        max_tokens = int(max_tokens or self.default_budget)
        base = self._summarize_large_objects(_plain(bundle))
        if target == "tool":
            data = self.sanitizer.sanitize_for_tool(base)
        elif target == "ui":
            data = self.sanitizer.sanitize_for_ui(base)
        elif target == "audit":
            data = self.sanitizer.sanitize_for_audit(base)
        else:
            data = self.sanitizer.sanitize_for_llm(base)

        data = self.summarize_old_context(data)
        data = self.keep_required_refs(data)
        if self.estimate_context_size(data) <= max_tokens:
            return data

        data = self._drop_low_priority_runtime_details(data)
        if self.estimate_context_size(data) <= max_tokens:
            return data

        data = self._shrink_evidence_and_positions(data)
        while self.estimate_context_size(data) > max_tokens and self._drop_one_history_message(data):
            pass
        data.setdefault("metadata", {})["window_token_estimate"] = self.estimate_context_size(data)
        data["metadata"]["window_max_tokens"] = max_tokens
        return data

    def _summarize_large_objects(self, data: dict[str, Any]) -> dict[str, Any]:
        data = deepcopy(data)
        portfolio = data.get("portfolio_context")
        if isinstance(portfolio, dict):
            raw_positions = portfolio.pop("raw_positions", None)
            if isinstance(raw_positions, list):
                portfolio["raw_positions_summary"] = {
                    "count": len(raw_positions),
                    "artifact_refs": list(portfolio.get("artifact_refs") or []),
                }
        evidence = data.get("evidence_context")
        if isinstance(evidence, dict):
            raw_evidence = evidence.pop("raw_evidence", None)
            if isinstance(raw_evidence, list):
                evidence["raw_evidence_summary"] = {
                    "count": len(raw_evidence),
                    "source_refs": list(evidence.get("source_refs") or []),
                }
        return data

    def _drop_low_priority_runtime_details(self, data: dict[str, Any]) -> dict[str, Any]:
        data = deepcopy(data)
        runtime = data.get("runtime_context")
        if isinstance(runtime, dict):
            runtime.pop("warnings", None)
            runtime.pop("errors", None)
            runtime.pop("stack_trace", None)
        data.pop("visibility_policy", None)
        return data

    def _shrink_evidence_and_positions(self, data: dict[str, Any]) -> dict[str, Any]:
        data = deepcopy(data)
        portfolio = data.get("portfolio_context")
        if isinstance(portfolio, dict) and isinstance(portfolio.get("positions_summary"), list):
            portfolio["positions_summary"] = portfolio["positions_summary"][:8]
        evidence = data.get("evidence_context")
        if isinstance(evidence, dict) and isinstance(evidence.get("evidence_summary"), list):
            evidence["evidence_summary"] = evidence["evidence_summary"][:8]
        return data

    @staticmethod
    def _drop_one_history_message(data: dict[str, Any]) -> bool:
        conversation = data.get("conversation_context")
        if not isinstance(conversation, dict):
            return False
        messages = conversation.get("recent_messages")
        if not isinstance(messages, list) or len(messages) <= 1:
            return False
        messages.pop(0)
        conversation["dropped_message_count"] = int(conversation.get("dropped_message_count") or 0) + 1
        return True
