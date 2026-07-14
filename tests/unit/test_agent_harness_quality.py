from __future__ import annotations

from evaluation.agent_harness.assertions import assert_case_result
from evaluation.agent_harness.metrics import compute_metrics
from evaluation.agent_harness.schemas import HarnessAssertion, HarnessCase, HarnessCaseResult, HarnessExpected
from database.repositories import AgentRepository


def _snapshot() -> dict:
    return {
        "run": {
            "status": "completed",
            "metadata_json": {
                "status_transitions": [
                    {"from": "created", "to": "planning", "reason": "test"}
                ]
            },
        },
        "tool_calls": [],
        "sources": [
            {
                "source_id": "src_1",
                "source_type": "rag_chunk",
                "database_record_id": "chunk_1",
                "snippet": "evidence",
            }
        ],
    }


def test_harness_answer_evidence_and_business_quality_pass(tmp_path):
    case = HarnessCase(
        case_id="quality_pass",
        query="分析 600519",
        user_id="u1",
        expected=HarnessExpected(
            required_answer_phrases=["风险"],
            required_answer_numbers=["12.34%"],
            require_disclaimer=True,
            required_evidence_ids=["chunk_1"],
            allowed_evidence_stock_codes=["600519"],
            max_evidence_publish_time="2026-07-01 15:00:00",
            read_only_no_business_writes=True,
        ),
    )
    result = {
        "answer": "风险提示：收入变化 12.34%。本回答不构成投资建议，不用于实盘交易。",
        "runtime": {"replan_count": 0},
        "tool_calls": [],
        "result": {
            "data": {
                "chunks": [
                    {
                        "chunk_id": "chunk_1",
                        "stock_code": "600519",
                        "publish_time": "2026-07-01 10:00:00",
                    }
                ]
            }
        },
    }

    assertions = assert_case_result(
        case,
        result=result,
        snapshot=_snapshot(),
        action_results=[],
        db_path=str(tmp_path / "agent.db"),
    )

    by_name = {item.name: item for item in assertions}
    assert by_name["answer_quality"].passed
    assert by_name["evidence_quality"].passed
    assert by_name["business_rule_safety"].passed


def test_harness_detects_wrong_stock_future_evidence_and_bad_answer(tmp_path):
    case = HarnessCase(
        case_id="quality_fail",
        query="分析 600519",
        user_id="u1",
        expected=HarnessExpected(
            required_answer_phrases=["风险"],
            forbidden_answer_phrases=["必然上涨"],
            require_disclaimer=True,
            allowed_evidence_stock_codes=["600519"],
            max_evidence_publish_time="2026-07-01 15:00:00",
        ),
    )
    result = {
        "answer": "该股票必然上涨。",
        "runtime": {"replan_count": 0},
        "tool_calls": [],
        "result": {
            "data": {
                "chunks": [
                    {
                        "chunk_id": "chunk_future_wrong_stock",
                        "stock_code": "000001",
                        "publish_time": "2026-07-02 10:00:00",
                    }
                ]
            }
        },
    }

    assertions = assert_case_result(
        case,
        result=result,
        snapshot=_snapshot(),
        action_results=[],
        db_path=str(tmp_path / "agent.db"),
    )

    by_name = {item.name: item for item in assertions}
    assert not by_name["answer_quality"].passed
    assert "风险" in by_name["answer_quality"].details["missing_phrases"]
    assert not by_name["evidence_quality"].passed
    assert by_name["evidence_quality"].details["wrong_stocks"] == ["000001"]
    assert by_name["evidence_quality"].details["future_rows"]


def test_harness_business_rule_safety_detects_writes(tmp_path):
    db_path = tmp_path / "agent.db"
    AgentRepository(db_path).upsert_action_proposal(
        {
            "plan_id": "plan_1",
            "user_id": "u1",
            "operation_type": "adjust_position",
            "plan_hash": "hash_1",
            "status": "pending",
            "before_state_summary": {},
            "proposed_changes": [],
            "after_state_preview": {},
            "warnings": [],
            "validation_results": [],
            "metadata": {},
        }
    )
    case = HarnessCase(
        case_id="business_write_fail",
        query="查看排名",
        user_id="u1",
        expected=HarnessExpected(read_only_no_business_writes=True),
    )

    assertions = assert_case_result(
        case,
        result={"answer": "", "runtime": {"replan_count": 0}, "tool_calls": [], "result": {}},
        snapshot=_snapshot(),
        action_results=[],
        db_path=str(db_path),
    )

    business = next(item for item in assertions if item.name == "business_rule_safety")
    assert not business.passed
    assert business.details["write_counts"]["action_proposals"] == 1


def test_harness_composite_metrics_include_quality_dimensions():
    case = HarnessCase(case_id="metrics", query="q")
    result = HarnessCaseResult(
        case=case,
        passed=True,
        latency_seconds=1.0,
        run_id="run_1",
        final_status="completed",
        result={"success": True},
        runtime_snapshot={},
        action_results=[],
        assertions=[
            HarnessAssertion("required_tools", True),
            HarnessAssertion("forbidden_tools", True),
            HarnessAssertion("state_transitions_recorded", True),
            HarnessAssertion("source_trace", True),
            HarnessAssertion("evidence_quality", True),
            HarnessAssertion("answer_quality", True),
            HarnessAssertion("confirmation_required_boundary", True),
            HarnessAssertion("duplicate_confirmation_safe", True),
            HarnessAssertion("business_rule_safety", True),
            HarnessAssertion("replan_limit", True),
        ],
        output_dir="",
        db_path="",
    )

    metrics = compute_metrics([result])

    assert metrics["source_quality_rate"] == 1.0
    assert metrics["answer_quality_rate"] == 1.0
    assert metrics["business_rule_pass_rate"] == 1.0
    assert metrics["agent_composite_score"] == 1.0
    assert metrics["agent_composite_weights"]["source"] + metrics["agent_composite_weights"]["safety"] > metrics["agent_composite_weights"]["tool"]
