from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from agent.collaboration.agent_directory import AgentDirectory, REPORT_WRITER, W06
from agent.collaboration.models import GraphAgentTask, ResultStatus
from agent.collaboration.report_validation import (
    build_report_policy,
    validate_report_output,
)
from agent.collaboration.workers.report_writer import run_report_writer


def _safe_results() -> list[dict]:
    return [
        {
            "task_id": "W02_portfolio",
            "status": "completed",
            "output_type": "PortfolioAnalysisResult",
            "payload": {
                "entity_catalog": [
                    {
                        "public_code": "601899",
                        "display_label": "紫金矿业",
                        "entity_ref": {
                            "node_id": "cn:security:sse:601899",
                            "locked": True,
                        },
                        "identity_source": "graph_identity",
                        "identity_locked": True,
                    }
                ],
                "display_positions": [
                    {
                        "public_code": "601899",
                        "display_label": "紫金矿业",
                        "quantity": 900.0,
                        "current_price": 32.15,
                    }
                ],
            },
            "summary": "已读取当前组合。",
            "confidence": 1.0,
        }
    ]


def _task() -> GraphAgentTask:
    return GraphAgentTask(
        task_id="W06_report",
        run_id="run-report",
        session_id="session-report",
        worker_id=W06,
        assigned_agent=REPORT_WRITER,
        objective="查看当前模拟盘账户和持仓",
        task_type="write_report",
        user_id="cht",
        args={
            "report_goal": "查看当前模拟盘账户和持仓",
            "reply_language": "zh",
        },
        inputs={
            "upstream_results": [
                {
                    "from_task_id": "W02_portfolio",
                    "expected_output_type": "PortfolioAnalysisResult",
                }
            ]
        },
        expected_output_type="FinalReport",
        dependency_task_ids=["W02_portfolio"],
    )


def _resolved_inputs() -> dict:
    return {
        "upstream_results": [
            {
                "from_task_id": "W02_portfolio",
                "status": "completed",
                "output_type": "PortfolioAnalysisResult",
                "payload_schema": "portfolio_analysis_result.v1",
                "payload_version": "v1",
                "payload": _safe_results()[0]["payload"],
                "summary": "已读取当前组合。",
                "evidence_refs": [],
                "artifact_refs": [],
                "confidence": 1.0,
            }
        ]
    }


def test_view_only_policy_rejects_risk_and_advice_scope() -> None:
    policy = build_report_policy("查看当前模拟盘账户和持仓", _safe_results())

    validation = validate_report_output(
        "当前持仓结构稳健，风险可控。建议持续关注行业新闻。",
        policy,
    )

    assert policy.view_only is True
    assert validation.valid is False
    codes = {item.code for item in validation.issues}
    assert "scope_violation" in codes
    assert "missing_strategy_worker_grounding" in codes


def test_entity_name_must_match_authoritative_graph_identity() -> None:
    policy = build_report_policy("查看当前模拟盘账户和持仓", _safe_results())

    validation = validate_report_output(
        "| 证券代码 | 证券名称 | 数量 |\n|---|---|---|\n| 601899 | 中国石油 | 900 |",
        policy,
    )

    assert validation.valid is False
    mismatch = next(item for item in validation.issues if item.code == "entity_mismatch")
    assert "紫金矿业" in mismatch.message


def test_report_writer_uses_one_targeted_repair_and_reuses_upstream_results() -> None:
    llm = SimpleNamespace(
        generate_text=Mock(
            side_effect=[
                "| 证券代码 | 证券名称 |\n|---|---|\n| 601899 | 中国石油 |\n\n风险可控，建议继续持有。",
                "当前持仓如下：\n\n| 证券代码 | 证券名称 | 数量 |\n|---|---|---:|\n| 601899 | 紫金矿业 | 900 |",
            ]
        )
    )

    result = run_report_writer(
        llm,
        _task(),
        {"W02_portfolio": _safe_results()[0]},
        "zh",
        resolved_inputs=_resolved_inputs(),
    )

    assert llm.generate_text.call_count == 2
    assert result.status == ResultStatus.COMPLETED
    assert "紫金矿业" in result.summary
    assert "中国石油" not in result.summary
    assert result.metadata["targeted_repair_used"] is True
    assert result.metadata["full_dag_replan_used"] is False
    assert result.metadata["upstream_results_reused"] is True
    repair_payload = llm.generate_text.call_args_list[1].kwargs["messages"][1]["content"]
    assert "entity_mismatch" in repair_payload
    assert "resolved_worker_inputs" in repair_payload


def test_report_writer_does_not_publish_second_invalid_report() -> None:
    llm = SimpleNamespace(
        generate_text=Mock(
            side_effect=[
                "| 601899 | 中国石油 |\n风险可控。",
                "| 601899 | 中国石油 |\n建议继续持有。",
            ]
        )
    )

    result = run_report_writer(
        llm,
        _task(),
        {"W02_portfolio": _safe_results()[0]},
        "zh",
        resolved_inputs=_resolved_inputs(),
    )

    assert result.status == ResultStatus.PARTIAL
    assert result.error["code"] == "report_output_validation_failed"
    assert result.metadata["targeted_repair_used"] is True
    assert result.metadata["targeted_repair_succeeded"] is False
    assert "中国石油" not in result.summary
    assert "未通过事实与职责边界校验" in result.summary


def test_w06_card_keeps_existing_role_and_adds_scope_boundaries() -> None:
    card = AgentDirectory().get(W06)

    assert card.role == REPORT_WRITER
    assert "重新查询业务数据" in card.non_responsibilities
    assert any("PortfolioRiskResult" in item for item in card.non_responsibilities)
    assert any("ReviewedProposal" in item for item in card.non_responsibilities)
    assert "不得根据代码或 position_id 猜测" in card.private_worker_prompt


def _view_only_plan_with_risk_worker() -> dict:
    return {
        "tasks": [
            {
                "task_id": "W02_portfolio",
                "worker_id": "W02",
                "objective": "读取当前模拟盘账户和持仓状态",
                "task_type": "query_portfolio_state",
                "args": {"user_id": "cht", "as_of_time": ""},
                "inputs": {},
                "constraints": [],
                "expected_output_type": "PortfolioAnalysisResult",
                "priority": 1,
            },
            {
                "task_id": "W04_risk",
                "worker_id": "W04",
                "objective": "分析当前组合风险",
                "task_type": "analyze_risk",
                "args": {"risk_question": "分析组合风险"},
                "inputs": {
                    "portfolio_state": {
                        "from_task_id": "W02_portfolio",
                        "expected_output_type": "PortfolioAnalysisResult",
                    }
                },
                "constraints": [],
                "expected_output_type": "PortfolioRiskResult",
                "priority": 2,
            },
            {
                "task_id": "W06_report",
                "worker_id": "W06",
                "objective": "汇总账户、持仓和风险分析",
                "task_type": "write_report",
                "args": {
                    "report_goal": "查看当前模拟盘账户和持仓并分析风险",
                    "reply_language": "zh",
                },
                "inputs": {
                    "upstream_results": [
                        {
                            "from_task_id": "W02_portfolio",
                            "expected_output_type": "PortfolioAnalysisResult",
                        },
                        {
                            "from_task_id": "W04_risk",
                            "expected_output_type": "PortfolioRiskResult",
                        },
                    ]
                },
                "constraints": [],
                "expected_output_type": "FinalReport",
                "priority": 3,
            },
        ]
    }


def test_planner_deterministically_rejects_risk_worker_for_view_only_request() -> None:
    from agent.collaboration.planner import CoordinatorPlanner
    from agent.collaboration.worker_contracts import WorkerContractViolation

    planner = CoordinatorPlanner(AgentDirectory(), llm_service=SimpleNamespace())

    try:
        planner._validate_payload(
            _view_only_plan_with_risk_worker(),
            request_mode="analysis",
            authoritative_ref_ids=set(),
            authoritative_user_id="cht",
            reply_language="zh",
            user_request="查看当前模拟盘账户和持仓",
        )
    except WorkerContractViolation as exc:
        assert "risk_worker_not_allowed_for_view_only_request" in str(exc)
    else:
        raise AssertionError("view-only plan must not include W04")


def test_view_only_policy_rejects_unrequested_orders_and_inference() -> None:
    policy = build_report_policy("查看当前模拟盘账户和持仓", _safe_results())

    validation = validate_report_output(
        "### 近期交易记录\n本次交易说明组合结构稳健。",
        policy,
    )

    codes = {item.code for item in validation.issues}
    assert "unrequested_detail_scope" in codes
    assert "unsupported_inference" in codes or "scope_violation" in codes


def test_portfolio_contract_exposes_authoritative_report_entities() -> None:
    card = AgentDirectory().get("W02")
    contract = card.task_contract("query_portfolio_state")
    payload_schema = contract.output_schema["properties"]["payload"]["anyOf"][1]

    assert "entity_catalog" in payload_schema["properties"]
    assert "display_positions" in payload_schema["properties"]
    assert "entity_catalog" in payload_schema["required"]
    assert "display_positions" in payload_schema["required"]
