from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


class SchedulerStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    PARTIAL_SUCCESS = "partial_success"


VALID_STEP_STATUSES = {
    SchedulerStatus.PENDING,
    SchedulerStatus.RUNNING,
    SchedulerStatus.SUCCESS,
    SchedulerStatus.FAILED,
    SchedulerStatus.SKIPPED,
    SchedulerStatus.PARTIAL_SUCCESS,
}


def now_text() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def make_run_id(prefix: str = "scheduled") -> str:
    return f"{prefix}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"


@dataclass
class StepStatus:
    step_name: str
    status: str = SchedulerStatus.PENDING
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0
    retry_count: int = 0
    error_type: str = ""
    error_message: str = ""
    traceback: str = ""
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StepStatus":
        return cls(**{**cls(step_name=str(data.get("step_name") or "")).to_dict(), **dict(data)})


@dataclass
class JobStatus:
    job_id: str
    run_id: str
    trade_date: str
    execution_source: str = "manual"
    started_at: str = field(default_factory=now_text)
    finished_at: str = ""
    duration_seconds: float = 0.0
    overall_status: str = SchedulerStatus.PENDING
    current_step: str = ""
    completed_steps: list[str] = field(default_factory=list)
    failed_steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    public_task_status: dict[str, Any] = field(default_factory=dict)
    user_task_status: dict[str, Any] = field(default_factory=dict)
    step_status: dict[str, StepStatus] = field(default_factory=dict)
    ranking_output_path: str = ""
    news_count: int = 0
    recommendation_count: int = 0
    paper_order_count: int = 0
    position_count: int = 0
    report_path: str = ""
    is_trading_day: bool = False
    plan_time: str = "17:30"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["step_status"] = {name: step.to_dict() for name, step in self.step_status.items()}
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobStatus":
        payload = dict(data)
        raw_steps = payload.get("step_status") or {}
        payload["step_status"] = {
            str(name): StepStatus.from_dict(step) if isinstance(step, dict) else step
            for name, step in raw_steps.items()
        }
        defaults = cls(job_id=str(payload.get("job_id") or ""), run_id=str(payload.get("run_id") or ""), trade_date=str(payload.get("trade_date") or "")).to_dict()
        defaults.update(payload)
        defaults["step_status"] = payload["step_status"]
        return cls(**defaults)
