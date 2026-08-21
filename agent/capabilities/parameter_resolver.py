"""Deterministic resolver for explicit user/either-owned business parameters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .models import BusinessParameterRequirement, CapabilityContract


@dataclass(frozen=True)
class ParameterGap:
    parameter_id: str
    semantic_role: str
    source_policy: str
    description: str
    expected_format: str = ""
    searched_sources: list[str] = field(default_factory=list)
    satisfy_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParameterResolution:
    satisfied: bool
    gaps: list[ParameterGap] = field(default_factory=list)

    @property
    def failure_kind(self) -> str:
        return "user_input_required" if self.gaps else "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "satisfied": self.satisfied,
            "failure_kind": self.failure_kind,
            "gaps": [item.to_dict() for item in self.gaps],
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


class BusinessParameterResolver:
    """Resolve only explicit business parameters before a Worker executes.

    Business-data sufficiency belongs to the domain analysis Worker because it
    reads the run ContextBundle directly. Runtime only prevents the Worker from
    inventing user-owned decision parameters.
    """

    @staticmethod
    def _gap(
        requirement: BusinessParameterRequirement,
        parameters: dict[str, Any],
    ) -> ParameterGap | None:
        if not requirement.required:
            return None
        candidates = list(requirement.satisfy_by or [requirement.parameter_id])
        non_empty = requirement.satisfaction_rule in {"non_empty", "one_of"}
        if any(_present(_lookup_path(parameters, key), non_empty=non_empty) for key in candidates):
            return None
        return ParameterGap(
            parameter_id=requirement.parameter_id,
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
        business_parameters: dict[str, Any] | None,
        available_parameters: dict[str, Any] | None = None,
    ) -> ParameterResolution:
        parameters = dict(available_parameters or {})
        parameters.update(dict(business_parameters or {}))
        gaps: list[ParameterGap] = []
        for contract in contracts:
            for requirement in contract.required_parameters:
                gap = self._gap(requirement, parameters)
                if gap is not None:
                    gaps.append(gap)
        return ParameterResolution(satisfied=not gaps, gaps=gaps)


__all__ = ["BusinessParameterResolver", "ParameterGap", "ParameterResolution"]
