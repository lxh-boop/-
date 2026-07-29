"""Main-owned protocol for Worker context requests and user clarification.

Workers emit structured requirements.  This module lets the Main Agent search
confirmed session memory, ask one sanitized business question, validate the
next user turn, and persist only confirmed clarification values.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from core.llm import LLMService

from .models import (
    ContextRequestCategory,
    MissingContextItem,
    WorkerContextRequest,
)
from .session_memory import SessionMemoryStore


_SECRET_KEYS = {
    "api_key",
    "authorization",
    "confirmation_token",
    "confirmation_token_hash",
    "cookie",
    "password",
    "secret",
    "token",
}
_USER_RESOLVABLE_CATEGORIES = {
    ContextRequestCategory.USER_INPUT_REQUIRED,
    ContextRequestCategory.MEMORY_LOOKUP_REQUIRED,
    ContextRequestCategory.AMBIGUOUS_REFERENCE,
}


@dataclass(frozen=True)
class ContextTurnDecision:
    action: str
    values: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    confidence: float = 0.0


def _is_secret_key(value: str) -> bool:
    key = str(value or "").strip().lower()
    return key in _SECRET_KEYS or any(
        marker in key for marker in ("api_key", "password", "secret", "token")
    )


def _dedupe_requirements(
    requests: Iterable[WorkerContextRequest],
) -> list[MissingContextItem]:
    result: list[MissingContextItem] = []
    seen: set[str] = set()
    for request in requests:
        for item in request.requirements:
            if not item.blocking or item.key in seen:
                continue
            seen.add(item.key)
            result.append(item)
    return result


def _value_matches_schema(value: Any, schema: dict[str, Any]) -> bool:
    wanted = str(schema.get("type") or "").strip().lower()
    if not wanted:
        return True
    expected = {
        "array": list,
        "boolean": bool,
        "integer": int,
        "number": (int, float),
        "object": dict,
        "string": str,
    }.get(wanted)
    return expected is None or isinstance(value, expected)


class MainContextHandoff:
    """Resolve Worker context requests without exposing Worker internals."""

    def __init__(
        self,
        *,
        memory: SessionMemoryStore,
        llm_service: LLMService,
    ) -> None:
        self.memory = memory
        self.llm_service = llm_service

    def memory_values(
        self,
        session_id: str,
        requests: Iterable[WorkerContextRequest],
    ) -> tuple[dict[str, Any], list[MissingContextItem]]:
        resolved: dict[str, Any] = {}
        unresolved: list[MissingContextItem] = []
        for item in _dedupe_requirements(requests):
            if (
                not item.allow_memory_lookup
                or item.category not in _USER_RESOLVABLE_CATEGORIES
                or _is_secret_key(item.key)
            ):
                unresolved.append(item)
                continue
            memory_item = self.memory.get(session_id, item.key)
            if memory_item is None or not memory_item.confirmed:
                unresolved.append(item)
                continue
            resolved[item.key] = memory_item.value
        return resolved, unresolved

    @staticmethod
    def clarification_question(
        requirements: Iterable[MissingContextItem],
        *,
        language: str,
    ) -> str:
        rows = list(requirements)
        user_rows = [
            item
            for item in rows
            if item.category in _USER_RESOLVABLE_CATEGORIES
            and not _is_secret_key(item.key)
        ]
        config_rows = [
            item
            for item in rows
            if item.category == ContextRequestCategory.SYSTEM_CONFIG_REQUIRED
            or _is_secret_key(item.key)
        ]
        if user_rows:
            parts: list[str] = []
            for item in user_rows[:4]:
                detail = item.description
                if item.expected_format:
                    detail += (
                        f"（格式：{item.expected_format}）"
                        if language != "en"
                        else f" (format: {item.expected_format})"
                    )
                if item.candidates:
                    labels = [
                        str(
                            candidate.get("label")
                            or candidate.get("name")
                            or candidate.get("value")
                            or ""
                        )
                        for candidate in item.candidates[:8]
                    ]
                    labels = [label for label in labels if label]
                    if labels:
                        detail += (
                            "；可选：" + "、".join(labels)
                            if language != "en"
                            else "; options: " + ", ".join(labels)
                        )
                parts.append(detail)
            if language == "en":
                return "Please provide or select: " + "; ".join(parts)
            return "请补充或选择：" + "；".join(parts)
        if config_rows:
            if language == "en":
                return (
                    "Required system configuration is unavailable. Configure it "
                    "through the application settings and retry; do not send "
                    "credentials in chat."
                )
            return (
                "缺少必要的系统配置。请在应用设置中完成配置后重试，"
                "不要在对话中发送密钥或凭证。"
            )
        if language == "en":
            return "The task is waiting for an internal dependency and cannot continue yet."
        return "任务正在等待内部依赖，当前暂时无法继续。"

    def resolve_user_turn(
        self,
        *,
        query: str,
        requests: Iterable[WorkerContextRequest],
        memory_summary: str,
        language: str,
        relation_type: str = "",
    ) -> ContextTurnDecision:
        requirements = [
            item
            for item in _dedupe_requirements(requests)
            if item.category in _USER_RESOLVABLE_CATEGORIES
            and not _is_secret_key(item.key)
        ]
        if not requirements:
            return ContextTurnDecision(
                action="new_request",
                reason="no_user_resolvable_context_requirements",
                confidence=1.0,
            )
        relation = str(relation_type or "").strip().lower()
        if relation == "cancellation":
            return ContextTurnDecision(
                action="cancel_waiting",
                reason="explicit_conversation_cancellation",
                confidence=1.0,
            )

        allowed_keys = {item.key for item in requirements}
        by_key = {item.key: item for item in requirements}

        def validate(payload: dict[str, Any]) -> None:
            action = str(payload.get("action") or "").strip().lower()
            if action not in {
                "provide_context",
                "new_request",
                "cancel_waiting",
            }:
                raise RuntimeError("invalid_context_turn_action")
            values = payload.get("values") or {}
            if not isinstance(values, dict):
                raise RuntimeError("invalid_context_turn_values")
            unexpected = set(values).difference(allowed_keys)
            if unexpected:
                raise RuntimeError(
                    "unexpected_context_value:" + ",".join(sorted(unexpected))
                )
            invalid = [
                key
                for key, value in values.items()
                if not _value_matches_schema(
                    value,
                    by_key[key].value_schema,
                )
            ]
            if invalid:
                raise RuntimeError(
                    "invalid_context_value_type:"
                    + ",".join(sorted(invalid))
                )

        payload = self.llm_service.generate_json(
            stage="main_agent_context_resume",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the Main Agent context-resume controller. "
                        "Decide whether the current user turn supplies requested "
                        "business context, starts a clearly new request, or cancels "
                        "the suspended request. Never infer missing values. Only "
                        "return keys listed in requirements. Do not request or "
                        "return credentials, internal tool parameters, worker "
                        "names, database identifiers, or implementation details. "
                        "Return strict JSON: "
                        '{"action":"provide_context|new_request|cancel_waiting",'
                        '"values":{},"reason":"","confidence":0.0}.'
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "current_user_turn": str(query or ""),
                            "requirements": [
                                {
                                    "key": item.key,
                                    "description": item.description,
                                    "expected_format": item.expected_format,
                                    "value_schema": item.value_schema,
                                    "candidates": item.candidates,
                                }
                                for item in requirements
                            ],
                            "session_memory_summary": str(memory_summary or "")[
                                :3000
                            ],
                            "reply_language": language,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            max_output_tokens=1000,
            validator=validate,
            operation="resolve_worker_context_user_turn",
        )
        action = str(payload.get("action") or "").strip().lower()
        values = {
            str(key): value
            for key, value in dict(payload.get("values") or {}).items()
            if str(key) in allowed_keys and not _is_secret_key(str(key))
        }
        if action == "provide_context" and not values:
            action = "new_request"
        try:
            confidence = max(
                0.0,
                min(1.0, float(payload.get("confidence") or 0.0)),
            )
        except (TypeError, ValueError):
            confidence = 0.0
        return ContextTurnDecision(
            action=action,
            values=values,
            reason=str(payload.get("reason") or "")[:500],
            confidence=confidence,
        )

    def remember_clarification(
        self,
        *,
        session_id: str,
        request_id: str,
        values: dict[str, Any],
    ) -> None:
        for key, value in values.items():
            if _is_secret_key(key):
                continue
            self.memory.put(
                session_id=session_id,
                key=key,
                value=value,
                value_type="user_clarification",
                summary=f"User supplied context for {key}.",
                source_type="user_clarification",
                source_ref=request_id,
                confirmed=True,
                confidence=1.0,
            )


__all__ = [
    "ContextTurnDecision",
    "MainContextHandoff",
]
