from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from skills.schemas import CORE_QUESTIONS, SkillResult, validate_action


REQUIRED_SKILL_MD_SECTIONS = (
    "Purpose",
    "Input",
    "Process",
    "Output Schema",
    "Constraints",
    "Examples",
)


@dataclass(frozen=True)
class SkillDefinition:
    """Metadata for a skill specification.

    Skills define task method, input/output contracts and guardrails.
    They do not query databases, call external APIs or run prediction models.
    """

    name: str
    purpose: str
    input_schema: str
    output_schema: str
    core_questions: tuple[str, ...] = CORE_QUESTIONS
    constraints: tuple[str, ...] = field(default_factory=tuple)


def validate_skill_result(result: SkillResult) -> SkillResult:
    validate_action(result.action)
    if not 0.0 <= result.confidence <= 1.0:
        raise ValueError("confidence must be in [0, 1]")
    return result


def require_keys(payload: dict[str, Any], required_keys: list[str]) -> None:
    missing = [key for key in required_keys if key not in payload]
    if missing:
        raise ValueError(f"missing required keys: {missing}")
