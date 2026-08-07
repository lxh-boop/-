"""Auditable Worker requests for additional context slots."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ContextRequest:
    requester_worker_id: str
    run_id: str
    task_id: str
    requested_slot_id: str
    entity_refs: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    freshness_policy: str = "request_default"
    authority_policy: str = "verified"


@dataclass(frozen=True)
class ContextResponse:
    status: Literal["granted", "missing", "denied", "ambiguous"]
    slot_id: str
    value_ref: str = ""
    value: Any = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ContextBroker:
    def __init__(self, *, slot_store: Any, access_policy: dict[str, set[str]] | None = None) -> None:
        self.slot_store = slot_store
        self.access_policy = dict(access_policy or {})
        self.audit: list[dict[str, Any]] = []

    def request(self, value: ContextRequest) -> ContextResponse:
        allowed = self.access_policy.get(value.requester_worker_id)
        if allowed is not None and value.requested_slot_id not in allowed:
            response = ContextResponse("denied", value.requested_slot_id, reason="worker_context_policy_denied")
        else:
            rows = self.slot_store.read(run_id=value.run_id, slot_id=value.requested_slot_id)
            if not rows:
                response = ContextResponse("missing", value.requested_slot_id, reason="slot_not_available")
            elif len(rows) > 1 and value.authority_policy == "single_authoritative":
                response = ContextResponse("ambiguous", value.requested_slot_id, reason="multiple_slot_producers")
            else:
                row = rows[-1]
                response = ContextResponse("granted", value.requested_slot_id, value_ref=row.value_ref, value=row.value)
        self.audit.append({"request": asdict(value), "response": response.to_dict()})
        return response
