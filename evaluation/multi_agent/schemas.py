from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


DIRECT_MODE = "direct"
MULTI_AGENT_MODE = "multi_agent"


@dataclass(frozen=True)
class PermissionCheck:
    role: str
    tool_name: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MultiAgentScenario:
    scenario_id: str
    name: str
    query: str
    tasks: list[dict[str, Any]]
    fixture: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    expected_min_sources: int = 0
    expect_multi_agent_path: bool = True
    expected_decision_source: str = ""
    expect_llm_planner_called: bool | None = None
    expect_semantic_observer: bool | None = None
    expect_replan: bool | None = None
    permission_checks: list[PermissionCheck] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "query": self.query,
            "tasks": self.tasks,
            "fixture": self.fixture,
            "tags": self.tags,
            "expected_min_sources": self.expected_min_sources,
            "expect_multi_agent_path": self.expect_multi_agent_path,
            "expected_decision_source": self.expected_decision_source,
            "expect_llm_planner_called": self.expect_llm_planner_called,
            "expect_semantic_observer": self.expect_semantic_observer,
            "expect_replan": self.expect_replan,
            "permission_checks": [item.to_dict() for item in self.permission_checks],
        }


@dataclass(frozen=True)
class BenchmarkRunResult:
    scenario_id: str
    scenario_name: str
    mode: str
    success: bool
    execution_status: str
    latency_seconds: float
    task_count: int
    successful_task_count: int
    tool_call_count: int
    permission_violation_count: int
    permission_violations: list[dict[str, Any]]
    structured_output_valid: bool
    structured_output_errors: list[str]
    handoff_expected_count: int
    handoff_completed_count: int
    missing_handoff_count: int
    evidence_source_count: int
    evidence_source_coverage: float
    partial_failure_expected: bool
    partial_failure_recovered: bool | None
    decision_source: str = ""
    route_correct: bool = True
    safety_route_correct: bool = True
    llm_planner_called: bool = False
    llm_planner_elapsed_ms: float = 0.0
    llm_planner_token_estimate: int = 0
    semantic_observer_triggered: bool = False
    replan_triggered: bool = False
    replan_success: bool | None = None
    invalid_replan_block_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    role_timeline: list[dict[str, Any]] = field(default_factory=list)
    agent_outputs: dict[str, Any] = field(default_factory=dict)
    raw_result: dict[str, Any] = field(default_factory=dict)
    output_dir: str = ""
    db_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
