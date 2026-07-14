from __future__ import annotations

from agent.executor import run_agent_request
from agent.intent_decomposition.layered_decomposer import decompose_intent
from agent.intent_decomposition.schemas import IntentDecomposition, WRITE_INTENTS
from agent.orchestration.multi_task_executor import (
    _observe_task_results,
    _validate_replan_candidates,
)
from agent.runtime import load_run_snapshot
from agent.runtime_reliability import RuntimeBudget, RuntimePolicy
from agent_control_center_utils import write_agent_fixture


def _llm_plan(query: str) -> IntentDecomposition:
    return IntentDecomposition.from_dict(
        {
            "tasks": [
                {
                    "task_id": "task_1",
                    "intent": "portfolio_state",
                    "parameters": {},
                    "depends_on": [],
                    "reason": "llm semantic scope",
                    "confidence": 0.9,
                },
                {
                    "task_id": "task_2",
                    "intent": "portfolio_risk",
                    "parameters": {},
                    "depends_on": ["task_1"],
                    "reason": "llm semantic scope",
                    "confidence": 0.9,
                },
            ],
            "confidence": 0.9,
        },
        query=query,
        route_layer="llm_semantic",
        diagnostics={"llm_used": True},
    )


def test_phase7_simple_request_uses_rule_without_llm(monkeypatch) -> None:
    called = {"value": False}

    def fail_if_called(*args, **kwargs):
        called["value"] = True
        raise AssertionError("LLM planner should not be called for explicit single intent")

    monkeypatch.setattr(
        "agent.intent_decomposition.layered_decomposer.decompose_with_llm",
        fail_if_called,
    )

    decomposition = decompose_intent("查看当前模拟盘持仓", llm_api_key="fake-key")

    assert called["value"] is False
    assert decomposition.supervisor_decision is not None
    assert decomposition.supervisor_decision.decision_source == "rule"
    assert decomposition.diagnostics["llm_planner_called"] is False


def test_phase7_ambiguous_readonly_request_can_use_llm(monkeypatch) -> None:
    called = {"value": False}

    def fake_llm(query: str, **kwargs):
        called["value"] = True
        return _llm_plan(query)

    monkeypatch.setattr(
        "agent.intent_decomposition.layered_decomposer.decompose_with_llm",
        fake_llm,
    )

    decomposition = decompose_intent("帮我看看当前组合哪里需要关注", llm_api_key="fake-key")

    assert called["value"] is True
    assert decomposition.supervisor_decision is not None
    assert decomposition.supervisor_decision.decision_source == "llm"
    assert decomposition.supervisor_decision.requires_write is False
    assert decomposition.diagnostics["llm_planner_called"] is True


def test_phase7_llm_write_task_is_blocked_and_falls_back(monkeypatch) -> None:
    def illegal_llm(query: str, **kwargs):
        return IntentDecomposition.from_dict(
            {
                "tasks": [
                    {
                        "task_id": "task_1",
                        "intent": "one_time_position_operation",
                        "parameters": {"stock_code": "000001"},
                        "depends_on": [],
                    }
                ],
                "confidence": 0.8,
            },
            query=query,
            route_layer="llm_semantic",
        )

    monkeypatch.setattr(
        "agent.intent_decomposition.layered_decomposer.decompose_with_llm",
        illegal_llm,
    )

    decomposition = decompose_intent("帮我看看当前组合哪里需要关注", llm_api_key="fake-key")

    assert decomposition.supervisor_decision is not None
    assert decomposition.supervisor_decision.decision_source == "fallback"
    assert all(task.intent not in WRITE_INTENTS for task in decomposition.tasks)
    assert any("LLM意图拆解失败" in item for item in decomposition.warnings)


def test_phase7_write_request_stays_on_hard_safety_chain(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM planner must not route protected writes")

    monkeypatch.setattr(
        "agent.intent_decomposition.layered_decomposer.decompose_with_llm",
        fail_if_called,
    )

    decomposition = decompose_intent("把 000001 加入模拟盘 5%", llm_api_key="fake-key")

    assert decomposition.supervisor_decision is not None
    assert decomposition.supervisor_decision.decision_source == "rule"
    assert decomposition.supervisor_decision.requires_write is True
    assert decomposition.tasks[0].intent == "one_time_position_operation"


def test_phase7_semantic_observer_is_gated() -> None:
    simple = _observe_task_results(
        {
            "task_1": {
                "task_id": "task_1",
                "intent": "portfolio_state",
                "success": True,
                "step_status": "succeeded",
                "data": {"positions": [{"stock_code": "000001"}]},
                "warnings": [],
                "errors": [],
            }
        },
        replan_count=0,
        replan_limit=2,
    )
    assert simple["semantic_observer"]["triggered"] is False

    missing_evidence = _observe_task_results(
        {
            "task_1": {
                "task_id": "task_1",
                "intent": "stock_rag",
                "success": True,
                "step_status": "succeeded",
                "data": {"chunks": []},
                "warnings": [],
                "errors": [],
            }
        },
        replan_count=0,
        replan_limit=2,
    )
    assert missing_evidence["semantic_observer"]["triggered"] is True
    assert set(missing_evidence["semantic_observer"]["result"]) == {
        "complete",
        "partial",
        "conflict",
        "replan_suggestion",
        "missing_information",
        "confidence",
    }


def test_phase7_invalid_replan_candidates_are_rejected() -> None:
    accepted, blocked = _validate_replan_candidates(
        [
            {
                "task_id": "task_2",
                "intent": "one_time_position_operation",
                "parameters": {"stock_code": "000001"},
                "depends_on": ["task_1"],
            }
        ],
        tasks_by_id={"task_1": {"task_id": "task_1", "intent": "stock_rag", "depends_on": []}},
        budget=RuntimeBudget(RuntimePolicy.default()),
    )

    assert accepted == []
    assert blocked[0]["reason"] == "write_task_not_allowed_in_replan"


def test_phase7_runtime_records_decision_source_and_observe(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, with_position=True)

    result = run_agent_request(
        "查看当前模拟盘持仓",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        llm_api_key="",
    )

    assert result["decomposition"]["supervisor_decision"]["decision_source"] == "rule"
    snapshot = load_run_snapshot(db_path, result["run_id"])
    metadata = snapshot["run"]["metadata_json"]
    assert metadata["supervisor_decision"]["decision_source"] == "rule"
    assert metadata["observe"]["observations"][0]["observe_layer"] == "deterministic"
