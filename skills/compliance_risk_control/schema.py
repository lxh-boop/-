from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ComplianceRiskControlInput:
    text: str
    action: str = "no_action"
    evidence_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ComplianceRiskControlOutput:
    passed: bool
    violations: list[str]
    sanitized_text: str
    required_disclaimer: str
    action: str
    metadata: dict[str, Any] = field(default_factory=dict)
