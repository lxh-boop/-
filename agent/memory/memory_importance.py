from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .memory_types import MemoryRecord, MemoryStatus, MemoryType


TYPE_BASE_SCORE = {
    MemoryType.WORKING: 0.25,
    MemoryType.EPISODIC: 0.45,
    MemoryType.SEMANTIC: 0.62,
    MemoryType.EVIDENCE: 0.52,
    MemoryType.PORTFOLIO: 0.70,
    MemoryType.REFLECTION: 0.50,
    MemoryType.PERCEPTUAL: 0.25,
}


@dataclass(frozen=True)
class MemoryImportanceScorer:
    def score(self, record: MemoryRecord | dict[str, Any]) -> float:
        score, _reasons = self.score_with_reasons(record)
        return score

    def score_with_reasons(self, record: MemoryRecord | dict[str, Any]) -> tuple[float, list[str]]:
        record = record if isinstance(record, MemoryRecord) else MemoryRecord.from_dict(record)
        reasons: list[str] = []
        score = TYPE_BASE_SCORE.get(record.memory_type, 0.4)
        reasons.append(f"type:{record.memory_type.value}")
        if record.status not in {MemoryStatus.ACTIVE, MemoryStatus.CANDIDATE}:
            return 0.0, [*reasons, f"status:{record.status.value}"]
        score += 0.15 * record.importance
        score += 0.10 * record.confidence
        if record.metadata.get("user_confirmed") or str(record.source_type).lower() in {
            "confirmed_user_preference",
            "profile_setting",
            "user_feedback",
        }:
            score += 0.10
            reasons.append("confirmed_user_source")
        if record.stock_codes:
            score += 0.04
            reasons.append("stock_codes")
        if record.topics:
            score += 0.03
            reasons.append("topics")
        if record.artifact_refs or record.source_refs:
            score += 0.04
            reasons.append("source_refs")
        if record.approval_refs:
            score += 0.03
            reasons.append("approval_refs")
        if str(record.metadata.get("operation_scope") or "").lower() == "one_time":
            score -= 0.25
            reasons.append("one_time_discount")
        return max(0.0, min(1.0, score)), reasons
