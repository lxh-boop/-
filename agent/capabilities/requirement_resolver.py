"""Deterministic pre-execution requirement resolution for capability contracts.

The resolver is business-agnostic. It does not know about news, stocks, risk or
specific Workers. It only evaluates the requirements declared by the current
CapabilityContract against materialized Slots and explicit business parameters.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .models import BusinessParameterRequirement, CapabilityContract, InputSlotRequirement
from .semantic_slots import missing_required_paths


@dataclass(frozen=True)
class RequirementGap:
    requirement_id: str
    kind: str
    semantic_role: str
    source_policy: str
    description: str
    expected_format: str = ""
    searched_sources: list[str] = field(default_factory=list)
    missing_paths: list[str] = field(default_factory=list)
    satisfy_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RequirementResolution:
    satisfied: bool
    system_gaps: list[RequirementGap] = field(default_factory=list)
    user_gaps: list[RequirementGap] = field(default_factory=list)

    @property
    def failure_kind(self) -> str:
        # Internal/system-resolvable gaps always take precedence. Runtime must not
        # ask the user while a missing upstream/system fact can still be repaired.
        if self.system_gaps:
            return "worker_input_slot_unresolved"
        if self.user_gaps:
            return "user_input_required"
        return "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "satisfied": self.satisfied,
            "failure_kind": self.failure_kind,
            "system_gaps": [item.to_dict() for item in self.system_gaps],
            "user_gaps": [item.to_dict() for item in self.user_gaps],
        }


def _present(value: Any, *, non_empty: bool = False) -> bool:
    if value is None:
        return False
    if not non_empty:
        return True
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _lookup_path(mapping: dict[str, Any], path: str) -> Any:
    node: Any = mapping
    for segment in [item for item in str(path or "").split(".") if item]:
        if not isinstance(node, dict) or segment not in node:
            return None
        node = node[segment]
    return node


class RequirementResolver:
    """Resolve public capability requirements before invoking a domain Worker."""

    @staticmethod
    def _slot_gap(
        requirement: InputSlotRequirement,
        resolved_inputs: dict[str, Any],
    ) -> RequirementGap | None:
        if not requirement.required:
            return None
        value = resolved_inputs.get(requirement.slot_id)
        non_empty = requirement.satisfaction_rule == "non_empty"
        missing_paths = (
            missing_required_paths(value, requirement.required_paths)
            if value is not None
            else list(requirement.required_paths)
        )
        if _present(value, non_empty=non_empty) and not missing_paths:
            return None
        return RequirementGap(
            requirement_id=requirement.slot_id,
            kind="slot",
            semantic_role=requirement.semantic_role or requirement.slot_id,
            source_policy=requirement.source_policy or "system",
            description=f"CapabilityContract required input Slot is unavailable or incomplete: {requirement.slot_id}",
            expected_format=requirement.schema_id or "Runtime semantic Slot",
            searched_sources=["resolved_input_bindings", "resolved_inputs"],
            missing_paths=missing_paths,
        )

    @staticmethod
    def _parameter_gap(
        requirement: BusinessParameterRequirement,
        parameters: dict[str, Any],
    ) -> RequirementGap | None:
        if not requirement.required:
            return None
        candidates = list(requirement.satisfy_by or [requirement.parameter_id])
        non_empty = requirement.satisfaction_rule in {"non_empty", "one_of"}
        if any(_present(_lookup_path(parameters, key), non_empty=non_empty) for key in candidates):
            return None
        return RequirementGap(
            requirement_id=requirement.parameter_id,
            kind="parameter",
            semantic_role=requirement.semantic_role or requirement.parameter_id,
            source_policy=requirement.source_policy or "user",
            description=(
                requirement.description
                or f"Required business parameter is missing: {requirement.parameter_id}"
            ),
            expected_format=requirement.expected_format,
            searched_sources=["task.business_parameters", "execution_context.available_parameters"],
            satisfy_by=candidates,
        )

    def resolve(
        self,
        *,
        contracts: list[CapabilityContract],
        resolved_inputs: dict[str, Any] | None,
        business_parameters: dict[str, Any] | None,
        available_parameters: dict[str, Any] | None = None,
    ) -> RequirementResolution:
        slots = dict(resolved_inputs or {})
        # Explicit task business parameters take precedence over generic runtime
        # available_parameters because they belong to this compiled capability.
        parameters = dict(available_parameters or {})
        parameters.update(dict(business_parameters or {}))

        system_gaps: list[RequirementGap] = []
        user_gaps: list[RequirementGap] = []
        for contract in contracts:
            for requirement in contract.required_inputs:
                gap = self._slot_gap(requirement, slots)
                if gap is None:
                    continue
                if gap.source_policy == "user":
                    user_gaps.append(gap)
                else:
                    # system + either: first let orchestration repair internal
                    # context. A later layer may ask the user only after system
                    # resolution paths are exhausted.
                    system_gaps.append(gap)
            for requirement in contract.required_parameters:
                gap = self._parameter_gap(requirement, parameters)
                if gap is None:
                    continue
                if gap.source_policy == "system":
                    system_gaps.append(gap)
                else:
                    user_gaps.append(gap)

        return RequirementResolution(
            satisfied=not system_gaps and not user_gaps,
            system_gaps=system_gaps,
            user_gaps=user_gaps,
        )


__all__ = ["RequirementGap", "RequirementResolution", "RequirementResolver"]
