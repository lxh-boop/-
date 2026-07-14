from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class HarnessExpected:
    required_tools: list[str] = field(default_factory=list)
    forbidden_tools: list[str] = field(default_factory=list)
    expected_status: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    max_replan_count: int = 2
    min_source_count: int = 0
    allow_partial_success: bool = True
    expect_commit_status: str = ""
    expect_duplicate_safe: bool = False
    required_answer_phrases: list[str] = field(default_factory=list)
    forbidden_answer_phrases: list[str] = field(default_factory=list)
    required_answer_numbers: list[str] = field(default_factory=list)
    require_disclaimer: bool = False
    required_evidence_ids: list[str] = field(default_factory=list)
    forbidden_evidence_ids: list[str] = field(default_factory=list)
    allowed_evidence_stock_codes: list[str] = field(default_factory=list)
    max_evidence_publish_time: str = ""
    read_only_no_business_writes: bool = False

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "HarnessExpected":
        payload = dict(data or {})
        return cls(
            required_tools=list(payload.get("required_tools") or []),
            forbidden_tools=list(payload.get("forbidden_tools") or []),
            expected_status=list(payload.get("expected_status") or []),
            requires_confirmation=bool(payload.get("requires_confirmation", False)),
            max_replan_count=int(payload.get("max_replan_count", 2)),
            min_source_count=int(payload.get("min_source_count", 0)),
            allow_partial_success=bool(payload.get("allow_partial_success", True)),
            expect_commit_status=str(payload.get("expect_commit_status") or ""),
            expect_duplicate_safe=bool(payload.get("expect_duplicate_safe", False)),
            required_answer_phrases=list(payload.get("required_answer_phrases") or []),
            forbidden_answer_phrases=list(payload.get("forbidden_answer_phrases") or []),
            required_answer_numbers=[str(item) for item in (payload.get("required_answer_numbers") or [])],
            require_disclaimer=bool(payload.get("require_disclaimer", False)),
            required_evidence_ids=[str(item) for item in (payload.get("required_evidence_ids") or [])],
            forbidden_evidence_ids=[str(item) for item in (payload.get("forbidden_evidence_ids") or [])],
            allowed_evidence_stock_codes=[str(item).split(".")[0].zfill(6) for item in (payload.get("allowed_evidence_stock_codes") or [])],
            max_evidence_publish_time=str(payload.get("max_evidence_publish_time") or ""),
            read_only_no_business_writes=bool(payload.get("read_only_no_business_writes", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HarnessCase:
    case_id: str
    query: str
    user_id: str = "default"
    setup: dict[str, Any] = field(default_factory=dict)
    expected: HarnessExpected = field(default_factory=HarnessExpected)
    actions: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "HarnessCase":
        return cls(
            case_id=str(data.get("case_id") or ""),
            query=str(data.get("query") or ""),
            user_id=str(data.get("user_id") or "default"),
            setup=dict(data.get("setup") or {}),
            expected=HarnessExpected.from_mapping(data.get("expected") or {}),
            actions=list(data.get("actions") or []),
            tags=list(data.get("tags") or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "query": self.query,
            "user_id": self.user_id,
            "setup": self.setup,
            "expected": self.expected.to_dict(),
            "actions": self.actions,
            "tags": self.tags,
        }


@dataclass(frozen=True)
class HarnessAssertion:
    name: str
    passed: bool
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HarnessCaseResult:
    case: HarnessCase
    passed: bool
    latency_seconds: float
    run_id: str
    final_status: str
    result: dict[str, Any]
    runtime_snapshot: dict[str, Any]
    action_results: list[dict[str, Any]]
    assertions: list[HarnessAssertion]
    output_dir: str
    db_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "case": self.case.to_dict(),
            "passed": self.passed,
            "latency_seconds": self.latency_seconds,
            "run_id": self.run_id,
            "final_status": self.final_status,
            "result": self.result,
            "runtime_snapshot": self.runtime_snapshot,
            "action_results": self.action_results,
            "assertions": [item.to_dict() for item in self.assertions],
            "output_dir": self.output_dir,
            "db_path": self.db_path,
        }
