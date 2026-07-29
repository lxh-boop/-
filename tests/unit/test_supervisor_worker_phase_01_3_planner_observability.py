from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.collaboration.planner import CoordinatorPlanningError
from agent.console_trace import finalize_flow_markdown, flow_event, get_flow_markdown_path
from agent.executor import _empty_failure, _failure_descriptor
from agent.graph.errors import GraphUnavailableError
from core.llm.contracts import LLMJSONError, LLMResponse
from core.llm.service import LLMService


@dataclass
class _FakeAdapter:
    outputs: list[str]

    def generate(self, **_: object) -> LLMResponse:
        content = self.outputs.pop(0)
        return LLMResponse(
            content=content,
            provider_id="fake",
            model_name="fake-model",
            profile_id="fake-profile",
            config_hash="fake-hash",
        )


@dataclass
class _FakeRegistry:
    adapter: _FakeAdapter

    def adapter_for(self, _: object) -> _FakeAdapter:
        return self.adapter


def _fake_settings() -> object:
    profile = SimpleNamespace(
        provider_id="fake",
        model_name="fake-model",
        profile_id="fake-profile",
        config_hash="fake-hash",
        deployment_mode="local",
        endpoint_scope="loopback",
    )
    return SimpleNamespace(profile=profile, credential="", is_configured=True)


def test_generate_json_emits_primary_and_repair_diagnostics() -> None:
    events: list[tuple[str, dict]] = []
    service = LLMService(
        settings=_fake_settings(),  # type: ignore[arg-type]
        registry=_FakeRegistry(
            _FakeAdapter(
                [
                    json.dumps({"tasks": [{"task_id": "W01_001"}]}),
                    json.dumps({"tasks": [{"task_id": "W06_001"}]}),
                ]
            )
        ),  # type: ignore[arg-type]
    )

    def reject(_: dict) -> None:
        raise CoordinatorPlanningError(
            "unknown_upstream_input_task"
        )

    with pytest.raises(LLMJSONError) as captured:
        service.generate_json(
            stage="graph_coordinator_planner",
            messages=[{"role": "user", "content": "test"}],
            max_output_tokens=100,
            validator=reject,
            event_callback=lambda name, payload: events.append((name, payload)),
        )

    diagnostics = getattr(captured.value, "diagnostics")
    assert diagnostics["primary"]["candidate"]["tasks"][0]["task_id"] == "W01_001"
    assert diagnostics["repair"]["candidate"]["tasks"][0]["task_id"] == "W06_001"
    assert diagnostics["primary"]["error_type"] == "CoordinatorPlanningError"
    assert diagnostics["repair"]["error_type"] == "CoordinatorPlanningError"
    assert [name for name, _ in events] == [
        "request_started",
        "response_received",
        "candidate_generated",
        "validation_failed",
        "repair_started",
        "repair_response_received",
        "repair_candidate_generated",
        "repair_failed",
    ]


def test_planning_failure_is_not_mapped_to_neo4j() -> None:
    planning = _failure_descriptor(
        LLMJSONError("unknown_upstream_input_task"),
        "zh",
    )
    graph = _failure_descriptor(GraphUnavailableError("neo4j down"), "zh")

    assert planning["code"] == "main_agent_planning_failed"
    assert "Worker" in planning["message"]
    assert "Neo4j" not in planning["message"]
    assert graph["code"] == "financial_graph_unavailable"


def test_failure_snapshot_keeps_rejected_candidate_diagnostics() -> None:
    error = LLMJSONError("repair failed")
    error.diagnostics = {
        "primary": {
            "candidate": {
                "tasks": [
                    {
                        "task_id": "W06_001",
                        "args": {"risk_question": "分析组合风险"},
                        "inputs": {
                            "portfolio_state": {
                                "from_task_id": "W01_001",
                                "expected_output_type": "PortfolioAnalysisResult",
                            }
                        },
                    }
                ]
            },
            "error_message": "unknown_upstream_input_task",
        }
    }
    failure = _empty_failure(
        exc=error,
        query="分析600519",
        user_id="cht",
        session_id="session",
        run_id="agent_run_test",
        language="zh",
    )

    planner = failure["orchestration"]["graph_runtime"]["planner"]
    assert planner["failure_code"] == "main_agent_planning_failed"
    assert planner["candidate_plan_diagnostics"]["primary"]["candidate"]
    assert failure["answer"].startswith("MainAgent")


def test_flow_markdown_uses_run_id_and_writes_live_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "agent_run_phase_01_3_test"
    monkeypatch.setenv("AGENT_FLOW_TRACE", "1")
    monkeypatch.setenv("AGENT_FLOW_MARKDOWN_DIR", str(tmp_path))

    flow_event(
        "GRAPH_REQUEST",
        {"raw_message": "分析600519"},
        run_id=run_id,
    )
    flow_event(
        "LOCAL_LLM_REQUEST_STARTED",
        {"stage": "graph_coordinator_planner"},
        run_id=run_id,
    )

    path = Path(get_flow_markdown_path(run_id))
    assert path.name == f"分析600519__{run_id}.md"
    text = path.read_text(encoding="utf-8")
    assert "LOCAL_LLM_REQUEST_STARTED" in text
    assert "本地模型规划请求开始" in text

    finalize_flow_markdown(
        run_id=run_id,
        question="分析600519",
        execution={
            "execution_status": "failed",
            "failure": {
                "code": "main_agent_planning_failed",
                "stage": "worker_planning",
            },
            "graph_runtime": {
                "planner": {
                    "candidate_plan_diagnostics": {
                        "primary": {"error_message": "dependency error"}
                    }
                },
                "worker_dag": {"tasks": []},
            },
            "graph_worker_results": {"items": [], "failed_count": 1},
            "errors": ["dependency error"],
        },
        runtime_status="failed",
        success=False,
        final_answer="MainAgent 规划失败。",
    )
    final_text = path.read_text(encoding="utf-8")
    assert "失败阶段与错误分类" in final_text
    assert "candidate_plan_diagnostics" in final_text


def test_reload_watches_only_source_directories() -> None:
    module = importlib.import_module("run_agent_api")
    directories = [Path(item) for item in module._reload_directories()]

    assert directories
    assert all(path.is_dir() for path in directories)
    assert all(path.name not in {"runtime", "logs", "outputs", "data", "models"} for path in directories)
