"""Deterministic classification of missing parameters, context and entities."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ContextSufficiencyResult:
    sufficient: bool
    missing_parameters: list[str] = field(default_factory=list)
    missing_context_slots: list[str] = field(default_factory=list)
    ambiguous_entities: list[dict[str, Any]] = field(default_factory=list)
    unresolved_entities: list[str] = field(default_factory=list)
    permission_issues: list[str] = field(default_factory=list)
    next_action: Literal["continue", "ask_user", "wait_context", "select_entity", "deny"] = "continue"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ContextAndEntitySufficiencyGate:
    def evaluate(
        self,
        *,
        missing_items: list[Any] | None = None,
        required_parameters: list[str] | None = None,
        available_parameters: dict[str, Any] | None = None,
        ambiguous_entities: list[dict[str, Any]] | None = None,
        permission_issues: list[str] | None = None,
    ) -> ContextSufficiencyResult:
        available = dict(available_parameters or {})
        missing_parameters = [
            str(key) for key in required_parameters or [] if available.get(str(key)) in (None, "")
        ]
        missing_context: list[str] = []
        unresolved: list[str] = []
        for item in missing_items or []:
            key = str(getattr(item, "key", "") or (item.get("key") if isinstance(item, dict) else ""))
            reason = str(getattr(item, "reason", "") or (item.get("reason") if isinstance(item, dict) else ""))
            if "parameter" in reason.lower() or key in missing_parameters:
                if key and key not in missing_parameters:
                    missing_parameters.append(key)
            elif "entity" in key.lower() or "graph" in key.lower():
                unresolved.append(key)
            elif key:
                missing_context.append(key)
        ambiguous = list(ambiguous_entities or [])
        denied = list(permission_issues or [])
        if denied:
            action = "deny"
        elif ambiguous:
            action = "select_entity"
        elif missing_parameters:
            action = "ask_user"
        elif missing_context or unresolved:
            action = "wait_context"
        else:
            action = "continue"
        return ContextSufficiencyResult(
            sufficient=action == "continue",
            missing_parameters=missing_parameters,
            missing_context_slots=missing_context,
            ambiguous_entities=ambiguous,
            unresolved_entities=unresolved,
            permission_issues=denied,
            next_action=action,
        )
