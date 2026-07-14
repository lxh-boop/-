from __future__ import annotations

import json
from typing import Any

from .observe_policy import ObservePolicy
from .observe_sanitizer import ObserveSanitizer
from .observation_types import (
    ObservationEvent,
    ObservationSeverity,
    ObservationSummary,
    ObservationType,
)


IMPORTANT_TYPES = {
    ObservationType.APPROVAL_REQUIRED,
    ObservationType.APPROVAL_DENIED,
    ObservationType.TOOL_ERROR,
    ObservationType.TOOL_PERMISSION_BLOCKED,
    ObservationType.CONTEXT_INSUFFICIENT,
    ObservationType.EVIDENCE_INSUFFICIENT,
    ObservationType.TASK_FAILED,
    ObservationType.USER_CLARIFICATION_NEEDED,
}


class ObservationWindow:
    def __init__(
        self,
        *,
        default_budget: int = 6000,
        policy: ObservePolicy | None = None,
        sanitizer: ObserveSanitizer | None = None,
    ) -> None:
        self.default_budget = int(default_budget or 6000)
        self.policy = policy or ObservePolicy.default()
        self.sanitizer = sanitizer or ObserveSanitizer(self.policy)

    def trim_observations_to_budget(
        self,
        observations: list[ObservationEvent | dict[str, Any]],
        *,
        budget: int | None = None,
        target: str = "llm",
    ) -> list[dict[str, Any]]:
        max_budget = int(budget or self.default_budget)
        normalized = [self._coerce(item) for item in observations or []]
        kept: list[dict[str, Any]] = []
        used = 0

        required = [item for item in normalized if self._is_required(item)]
        recent = [item for item in normalized if item not in required]

        for item in [*required, *reversed(recent)]:
            safe = self._sanitize(item, target=target)
            size = self.estimate_observation_size(safe)
            if used + size <= max_budget or self._is_required(item):
                kept.append(safe)
                used += size
            else:
                summary = self.summarize_old_observations([item])[0].to_dict()
                size = self.estimate_observation_size(summary)
                if used + size <= max_budget:
                    kept.append(summary)
                    used += size
        return sorted(kept, key=lambda row: str(row.get("created_at") or row.get("observation_id") or ""))

    def summarize_old_observations(
        self,
        observations: list[ObservationEvent | dict[str, Any]],
    ) -> list[ObservationSummary]:
        summaries: list[ObservationSummary] = []
        for raw in observations or []:
            item = self._coerce(raw)
            safe = self.sanitizer.sanitize_for_context(item)
            summaries.append(
                ObservationSummary(
                    observation_id=str(safe.get("observation_id") or item.observation_id),
                    observation_type=item.observation_type,
                    status=item.status,
                    severity=item.severity,
                    summary=str(safe.get("summary") or item.summary or item.observation_type.value),
                    artifact_refs=list(safe.get("artifact_refs") or []),
                    context_refs=list(safe.get("context_refs") or []),
                    approval_refs=list(safe.get("approval_refs") or []),
                    replan_required=self.policy.requires_replan_check(item),
                )
            )
        return summaries

    def keep_required_observations(
        self,
        observations: list[ObservationEvent | dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            self.sanitizer.sanitize_for_context(item)
            for item in (self._coerce(raw) for raw in observations or [])
            if self._is_required(item)
        ]

    @staticmethod
    def estimate_observation_size(observation: ObservationEvent | dict[str, Any]) -> int:
        value = observation.to_dict() if hasattr(observation, "to_dict") else dict(observation or {})
        return len(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))

    def _sanitize(self, item: ObservationEvent, *, target: str) -> dict[str, Any]:
        if target == "ui":
            return self.sanitizer.sanitize_for_ui(item)
        if target == "context":
            return self.sanitizer.sanitize_for_context(item)
        if target == "audit":
            return self.sanitizer.sanitize_for_audit(item)
        return self.sanitizer.sanitize_for_llm(item)

    @staticmethod
    def _coerce(item: ObservationEvent | dict[str, Any]) -> ObservationEvent:
        return item if isinstance(item, ObservationEvent) else ObservationEvent.from_dict(dict(item or {}))

    @staticmethod
    def _is_required(item: ObservationEvent) -> bool:
        return (
            item.severity == ObservationSeverity.BLOCKING
            or item.observation_type in IMPORTANT_TYPES
        )
