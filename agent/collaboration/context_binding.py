from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class EntityScope(str, Enum):
    EXPLICIT_ENTITIES = "explicit_entities"
    CONVERSATION_FOCUS = "conversation_focus"
    PORTFOLIO = "portfolio"
    ACCOUNT = "account"
    GLOBAL = "global"
    NONE = "none"


class ReferenceEntityType(str, Enum):
    SECURITY = "security"
    PORTFOLIO = "portfolio"
    ACCOUNT = "account"
    EVENT = "event"
    UNKNOWN = "unknown"
    NONE = "none"


@dataclass(frozen=True)
class ContextBinding:
    """Request-local entity/context authority selected by RequestBundle decomposition.

    This is not a routing mode. It only describes which financial object scope
    the current Request is allowed to resolve/inherit.
    """

    entity_scope: EntityScope = EntityScope.NONE
    inherit_previous_focus: bool = False
    reference_entity_type: ReferenceEntityType = ReferenceEntityType.NONE
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_scope": self.entity_scope.value,
            "inherit_previous_focus": bool(self.inherit_previous_focus),
            "reference_entity_type": self.reference_entity_type.value,
            "reason": str(self.reason or ""),
        }


__all__ = ["ContextBinding", "EntityScope", "ReferenceEntityType"]
