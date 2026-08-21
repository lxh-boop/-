"""RequestBundle ready-batch execution primitives for V23.0.13."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SharedRunContext:
    """Immutable-by-contract parent-run snapshot.

    Callers receive deep copies through ``for_request``; no Request may write
    back into this snapshot. Request-local GraphRef/Need/Task/Completion data is
    intentionally excluded.
    """

    user_id: str
    session_id: str
    run_id: str
    user_profile_snapshot: dict[str, Any] = field(default_factory=dict)
    session_preference_snapshot: dict[str, Any] = field(default_factory=dict)
    global_market_context: dict[str, Any] = field(default_factory=dict)
    worker_public_catalog: list[dict[str, Any]] = field(default_factory=list)
    capability_registry_snapshot: dict[str, Any] = field(default_factory=dict)
    runtime_configuration: dict[str, Any] = field(default_factory=dict)
    shared_context_refs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy({
            "schema_version": "shared_run_context.v1",
            "user_id": self.user_id,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "user_profile_snapshot": self.user_profile_snapshot,
            "session_preference_snapshot": self.session_preference_snapshot,
            "global_market_context": self.global_market_context,
            "worker_public_catalog": self.worker_public_catalog,
            "capability_registry_snapshot": self.capability_registry_snapshot,
            "runtime_configuration": self.runtime_configuration,
            "shared_context_refs": self.shared_context_refs,
        })

    def for_request(self) -> dict[str, Any]:
        # Every Request gets an isolated copy. Mutation cannot affect siblings.
        return self.to_dict()


@dataclass
class SessionMutationProposal:
    request_id: str
    source_index: int
    operations: list[dict[str, Any]] = field(default_factory=list)

    def add_put(self, **kwargs: Any) -> None:
        self.operations.append({"operation": "put", **copy.deepcopy(kwargs)})

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "session_mutation_proposal.v1",
            "request_id": self.request_id,
            "source_index": int(self.source_index),
            "operations": copy.deepcopy(self.operations),
        }


class BatchSessionMutationCommitter:
    """Deterministically commit Request-local session proposals at a barrier."""

    FOCUS_KEYS = {"active_graph_refs"}

    def __init__(self, session_state: Any) -> None:
        self.session_state = session_state

    @staticmethod
    def _rank(proposal: SessionMutationProposal) -> tuple[int, str]:
        return (int(proposal.source_index), str(proposal.request_id))

    def commit(self, proposals: list[SessionMutationProposal]) -> dict[str, Any]:
        ordered = sorted(proposals, key=self._rank)
        # For focus keys, source order determines the winner, never thread finish order.
        last_focus_op: dict[str, tuple[SessionMutationProposal, dict[str, Any]]] = {}
        normal: list[tuple[SessionMutationProposal, dict[str, Any]]] = []
        conflicts: list[dict[str, Any]] = []
        seen: dict[str, list[str]] = {}
        for proposal in ordered:
            for operation in proposal.operations:
                if operation.get("operation") != "put":
                    continue
                key = str(operation.get("key") or "")
                seen.setdefault(key, []).append(proposal.request_id)
                if key in self.FOCUS_KEYS or key.startswith("typed_graph_focus:"):
                    last_focus_op[key] = (proposal, operation)
                else:
                    normal.append((proposal, operation))
        for key, request_ids in seen.items():
            if len(set(request_ids)) > 1:
                conflicts.append({
                    "key": key,
                    "request_ids": list(dict.fromkeys(request_ids)),
                    "resolution": "source_order_last_wins" if key in self.FOCUS_KEYS or key.startswith("typed_graph_focus:") else "session_store_conflict_policy",
                })
        committed: list[dict[str, Any]] = []
        for proposal, operation in [*normal, *[last_focus_op[key] for key in sorted(last_focus_op)]]:
            kwargs = {key: value for key, value in operation.items() if key != "operation"}
            outcome = self.session_state.put(**kwargs)
            committed.append({
                "request_id": proposal.request_id,
                "key": str(operation.get("key") or ""),
                "changed": bool(getattr(outcome, "changed", True)),
                "conflict": bool(getattr(outcome, "conflict", False)),
            })
        return {
            "schema_version": "request_batch_session_commit.v1",
            "proposal_count": len(proposals),
            "operation_count": sum(len(item.operations) for item in proposals),
            "committed": committed,
            "conflicts": conflicts,
        }


__all__ = ["BatchSessionMutationCommitter", "SessionMutationProposal", "SharedRunContext"]
