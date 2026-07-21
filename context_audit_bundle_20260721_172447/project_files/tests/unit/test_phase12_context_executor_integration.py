from __future__ import annotations

import json

from agent.context import ContextBundle
from agent.executor import run_agent_request
from agent.goal_planning import build_goal_planning_trace
from agent.intent_decomposition.schemas import IntentDecomposition, IntentTask
from agent_control_center_utils import write_agent_fixture


def test_executor_creates_phase12_context_bundle_snapshot(tmp_path):
    output_dir, db_path = write_agent_fixture(tmp_path, user_id="u1", with_position=True)

    result = run_agent_request(
        "查看当前模拟盘持仓",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        reply_language="zh",
    )

    phase12 = result["context"]["phase12_context"]
    encoded = json.dumps(phase12, ensure_ascii=False, sort_keys=True)

    assert result["success"] is True
    assert phase12["context_id"].startswith("context_")
    assert "llm_context" in phase12
    assert "minimal_context" in phase12
    assert "confirmation_token" not in encoded
    assert "agent_quant.db" not in encoded
    assert "confirmation_token" not in json.dumps(result.get("context") or {}, ensure_ascii=False, sort_keys=True)
    assert (output_dir / "context_snapshots" / "u1").exists()


def test_user_goal_and_task_plan_read_context_bundle_refs():
    bundle = ContextBundle(user_id="u1", conversation_id="conv1", run_id="run1")
    bundle.artifact_context.artifact_refs = [{"artifact_id": "artifact_keep"}]
    bundle.artifact_context.readable_artifact_ids = ["artifact_keep"]
    bundle.approval_context.pending_plan_id = "plan_keep"
    bundle.approval_context.plan_hash = "hash_keep"
    bundle.approval_context.token_present = True
    decomposition = IntentDecomposition(
        query="分析当前组合风险",
        route_layer="rule",
        tasks=[
            IntentTask(task_id="task_1", intent="portfolio_state", confidence=0.9),
            IntentTask(task_id="task_2", intent="portfolio_risk", depends_on=["task_1"], confidence=0.8),
        ],
        confidence=0.9,
    )

    trace = build_goal_planning_trace(
        "分析当前组合风险",
        decomposition,
        context={"context_bundle": bundle.to_minimal_context(), "user_id": "u1"},
    )

    assert trace["user_goal"]["system_generated_parameters"]["context_id"] == bundle.context_id
    assert "artifact_keep" in trace["user_goal"]["inherited_parameters"]["available_context_refs"]
    assert "plan_keep" in trace["user_goal"]["inherited_parameters"]["available_context_refs"]
    assert "artifact_keep" in trace["task_plan"]["required_artifacts"]
    assert "plan_keep" in trace["task_plan"]["required_artifacts"]
