from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


@dataclass(frozen=True)
class RetrievalCase:
    case_id: str
    query: str
    relevant_ids: tuple[str, ...]
    retrieved_ids: tuple[str, ...]
    latency_ms: float = 0.0


@dataclass(frozen=True)
class RetrievalMetrics:
    case_count: int
    hit_rate_at_k: float
    mean_reciprocal_rank: float
    recall_at_k: float
    precision_at_k: float
    average_latency_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_retrieval(cases: Iterable[RetrievalCase]) -> RetrievalMetrics:
    rows = list(cases)
    if not rows:
        return RetrievalMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0)
    hits: list[float] = []
    reciprocal_ranks: list[float] = []
    recalls: list[float] = []
    precisions: list[float] = []
    latencies: list[float] = []
    for case in rows:
        relevant = set(case.relevant_ids)
        retrieved = list(case.retrieved_ids)
        overlap = relevant & set(retrieved)
        hits.append(1.0 if overlap else 0.0)
        rank = next((index for index, item in enumerate(retrieved, start=1) if item in relevant), 0)
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
        recalls.append(len(overlap) / max(1, len(relevant)))
        precisions.append(len(overlap) / max(1, len(retrieved)))
        latencies.append(max(0.0, float(case.latency_ms)))
    return RetrievalMetrics(
        case_count=len(rows),
        hit_rate_at_k=mean(hits),
        mean_reciprocal_rank=mean(reciprocal_ranks),
        recall_at_k=mean(recalls),
        precision_at_k=mean(precisions),
        average_latency_ms=mean(latencies),
    )


def load_cases(path: str | Path) -> list[RetrievalCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else payload.get("cases", [])
    return [
        RetrievalCase(
            case_id=str(row.get("case_id") or index),
            query=str(row.get("query") or ""),
            relevant_ids=tuple(str(item) for item in row.get("relevant_ids") or []),
            retrieved_ids=tuple(str(item) for item in row.get("retrieved_ids") or []),
            latency_ms=float(row.get("latency_ms") or 0.0),
        )
        for index, row in enumerate(rows, start=1)
        if isinstance(row, dict)
    ]
