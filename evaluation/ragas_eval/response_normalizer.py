from __future__ import annotations

import re
from dataclasses import dataclass, field

from scoring.schemas import COMPLIANCE_DISCLAIMER


PROJECT_DISCLAIMER = "本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。"

STATUS_PATTERNS = [
    re.compile(r"^共找到\s*\d+\s*条\s*RAG\s*证据[。.!！]?$", re.IGNORECASE),
    re.compile(r"^Found\s+\d+\s+RAG\s+evidence\s+chunk(?:\(s\)|s)?[。.!！]?$", re.IGNORECASE),
]

BULLET_CITATION_PATTERN = re.compile(r"^\s*[-*]\s*\[[^\]]+\]\s*")


@dataclass(slots=True)
class NormalizedResponse:
    evaluated_response: str
    normalization_method: str = "deterministic_boilerplate_removal"
    removed_text: list[str] = field(default_factory=list)
    removed_formatting: list[str] = field(default_factory=list)


def normalize_response_for_ragas(response: str) -> NormalizedResponse:
    """Remove only fixed non-business boilerplate from the actual response.

    This function must not summarize, rewrite, reorder, or add facts. It can
    only delete fixed disclaimers/status lines and strip pure display markers.
    """

    text = str(response or "")
    removed_text: list[str] = []
    removed_formatting: list[str] = []
    kept_lines: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == COMPLIANCE_DISCLAIMER or line == PROJECT_DISCLAIMER:
            removed_text.append(line)
            continue
        if any(pattern.match(line) for pattern in STATUS_PATTERNS):
            removed_text.append(line)
            continue
        cleaned = BULLET_CITATION_PATTERN.sub("", line)
        if cleaned != line:
            removed_formatting.append(line[: len(line) - len(cleaned)])
        kept_lines.append(cleaned.strip())

    return NormalizedResponse(
        evaluated_response="\n".join(line for line in kept_lines if line).strip(),
        removed_text=removed_text,
        removed_formatting=removed_formatting,
    )
