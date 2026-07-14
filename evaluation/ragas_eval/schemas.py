from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def normalize_stock_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    code = text.split(".")[0]
    digits = "".join(ch for ch in code if ch.isdigit())
    return digits.zfill(6) if digits else ""


def ensure_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def parse_decision_time(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("decision_time is required")
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"decision_time must be ISO datetime with timezone: {text}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"decision_time must include timezone: {text}")
    return dt.astimezone(LOCAL_TZ)


def parse_optional_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        for fmt in [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y%m%d %H:%M:%S",
            "%Y%m%d %H:%M",
            "%Y-%m-%d",
            "%Y%m%d",
        ]:
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                dt = None
        if dt is None:
            try:
                dt = datetime.fromisoformat(text)
            except ValueError:
                return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(LOCAL_TZ)


def decision_time_for_project_filter(value: datetime) -> str:
    """Return a local naive string compatible with existing metadata_filter."""

    return value.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")


@dataclass(slots=True)
class EvaluationCase:
    case_id: str
    user_input: str
    stock_code: str
    decision_time: datetime
    reference: str = ""
    reference_context_ids: list[str] = field(default_factory=list)
    actual_response: str = ""
    response_run_id: str = ""
    response_source: str = ""
    allowed_related_stock_codes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "EvaluationCase":
        warnings: list[str] = []
        case_id = str(data.get("case_id") or "").strip()
        if not case_id:
            raise ValueError("case_id is required")
        user_input = str(data.get("user_input") or "").strip()
        if not user_input:
            raise ValueError(f"case_id={case_id}: user_input cannot be empty")
        decision_time = parse_decision_time(data.get("decision_time"))
        stock_code = normalize_stock_code(data.get("stock_code"))
        if not stock_code:
            warnings.append("stock_code is missing or cannot be normalized")

        raw_ref_ids = data.get("reference_context_ids")
        if raw_ref_ids is None:
            reference_context_ids: list[str] = []
            warnings.append("reference_context_ids missing; ID recall metrics will be skipped")
        elif not isinstance(raw_ref_ids, list):
            raise ValueError(f"case_id={case_id}: reference_context_ids must be a list")
        else:
            reference_context_ids = [str(item) for item in raw_ref_ids if str(item or "").strip()]

        reference = str(data.get("reference") or "").strip()
        if not reference:
            warnings.append("reference missing; reference-dependent metrics will be skipped")

        return cls(
            case_id=case_id,
            user_input=user_input,
            stock_code=stock_code,
            decision_time=decision_time,
            reference=reference,
            reference_context_ids=reference_context_ids,
            actual_response=str(data.get("actual_response") or data.get("response") or ""),
            response_run_id=str(data.get("response_run_id") or ""),
            response_source=str(data.get("response_source") or ""),
            allowed_related_stock_codes=[
                normalize_stock_code(item) for item in ensure_list(data.get("allowed_related_stock_codes"))
                if normalize_stock_code(item)
            ],
            tags=[str(item) for item in ensure_list(data.get("tags")) if str(item or "").strip()],
            metadata=dict(data.get("metadata") or {}),
            warnings=warnings,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["decision_time"] = self.decision_time.isoformat()
        return payload


@dataclass(slots=True)
class RetrievedContext:
    chunk_id: str
    text: str
    rank: int
    document_id: str | None = None
    parent_id: str | None = None
    event_id: str | None = None
    title: str | None = None
    stock_codes: list[str] = field(default_factory=list)
    publish_time: datetime | None = None
    source: str | None = None
    raw_score: float | None = None
    retrieval_sources: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["publish_time"] = self.publish_time.isoformat() if self.publish_time else None
        return payload


@dataclass(slots=True)
class DatasetLoadResult:
    cases: list[EvaluationCase]
    errors: list[dict[str, Any]]
    warnings: list[dict[str, Any]]


@dataclass(slots=True)
class AnswerResult:
    response: str
    cited_chunk_ids: list[str]
    model_name: str = "deterministic_agent_stock_rag_summary"
    prompt_version: str = "production_stock_rag_summary_v1"
    latency_ms: float = 0.0
    token_usage: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass(slots=True)
class CaseRunResult:
    case: EvaluationCase
    retrieved_contexts: list[RetrievedContext] = field(default_factory=list)
    response: str = ""
    cited_chunk_ids: list[str] = field(default_factory=list)
    answer_metadata: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    stage: str = ""
    latency_ms: float = 0.0

    def to_json_record(self) -> dict[str, Any]:
        return {
            "case_id": self.case.case_id,
            "user_input": self.case.user_input,
            "stock_code": self.case.stock_code,
            "decision_time": self.case.decision_time.isoformat(),
            "reference": self.case.reference,
            "reference_context_ids": self.case.reference_context_ids,
            "response_run_id": self.case.response_run_id,
            "response_source": self.case.response_source,
            "allowed_related_stock_codes": self.case.allowed_related_stock_codes,
            "tags": self.case.tags,
            "metadata": self.case.metadata,
            "response": self.response,
            "cited_chunk_ids": self.cited_chunk_ids,
            "retrieved_context_ids": [item.chunk_id for item in self.retrieved_contexts],
            "retrieved_contexts": [item.text for item in self.retrieved_contexts],
            "retrieved_context_metadata": [item.to_dict() for item in self.retrieved_contexts],
            "answer_metadata": self.answer_metadata,
            "metrics": self.metrics,
            "warnings": self.warnings,
            "error": self.error,
            "stage": self.stage,
            "latency_ms": self.latency_ms,
        }
