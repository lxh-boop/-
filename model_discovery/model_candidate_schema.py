from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


CANDIDATE_FIELDS = [
    "candidate_id",
    "model_name",
    "category",
    "source_type",
    "source_url",
    "paper_url",
    "github_url",
    "hf_url",
    "has_pretrained_weight",
    "weight_url",
    "has_training_code",
    "has_inference_code",
    "data_format_required",
    "input_type",
    "output_type",
    "task_type",
    "license",
    "stars",
    "last_update",
    "dependency_risk",
    "windows_compatibility",
    "python_version_required",
    "estimated_difficulty",
    "priority",
    "status",
    "notes",
]


DISCLAIMER = "回测结果仅代表历史数据上的模型表现，不代表未来收益，不构成投资建议。"


@dataclass
class ModelCandidate:
    candidate_id: str
    model_name: str
    category: str
    source_type: str
    source_url: str
    paper_url: str = ""
    github_url: str = ""
    hf_url: str = ""
    has_pretrained_weight: bool = False
    weight_url: str = ""
    has_training_code: bool = False
    has_inference_code: bool = False
    data_format_required: str = ""
    input_type: str = ""
    output_type: str = ""
    task_type: str = ""
    license: str = ""
    stars: int | None = None
    last_update: str = ""
    dependency_risk: str = "unknown"
    windows_compatibility: str = "unknown"
    python_version_required: str = ""
    estimated_difficulty: str = "medium"
    priority: int = 50
    status: str = "candidate"
    notes: str = ""
    discovered_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        return {field_name: row.get(field_name, "") for field_name in CANDIDATE_FIELDS}


def normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "downloaded"}


def infer_category(candidate: ModelCandidate) -> str:
    if candidate.category:
        return candidate.category
    if candidate.has_pretrained_weight:
        return "A"
    if candidate.has_training_code and candidate.has_inference_code:
        return "B"
    if candidate.source_type in {"paper", "arxiv"}:
        return "C"
    return "C"


def normalize_candidate(candidate: ModelCandidate) -> ModelCandidate:
    candidate.has_pretrained_weight = normalize_bool(candidate.has_pretrained_weight)
    candidate.has_training_code = normalize_bool(candidate.has_training_code)
    candidate.has_inference_code = normalize_bool(candidate.has_inference_code)
    candidate.category = infer_category(candidate)
    if not candidate.source_url:
        candidate.source_url = candidate.github_url or candidate.hf_url or candidate.paper_url
    return candidate
