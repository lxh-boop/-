from __future__ import annotations

from agent.collaboration.agent_directory import AgentDirectory, REPORT_WRITER
from agent.collaboration.completion import COMPLETION_REPORT_VERSION
from agent.collaboration.models import GraphAgentTask, ResultStatus
from agent.collaboration.workers.report_writer import run_report_writer
from agent.graph.contracts import GraphNodeKind, GraphRef
from agent.worker_tools.evidence import _deduplicate_records


def _focus_ref() -> GraphRef:
    return GraphRef(
        graph_id="financial_graph",
        node_id="cn:security:sse:600519",
        node_kind=GraphNodeKind.OBJECT,
        role="focus",
        source="test",
        locked=True,
    )


def test_evidence_records_are_deduplicated_by_shared_identity_value() -> None:
    rows = [
        {
            "source_id": "news_same",
            "title": "direct title",
            "text": "short",
            "_retrieved_by": "news_and_announcements",
        },
        {
            "news_id": "news_same",
            "chunk_id": "chunk_1",
            "title": "rag title",
            "text": "a much richer full text from rag",
            "_retrieved_by": "rag_evidence",
        },
        {
            "news_id": "news_other",
            "title": "other",
            "text": "other text",
            "_retrieved_by": "rag_evidence",
        },
    ]

    records, diagnostics = _deduplicate_records(rows)

    assert diagnostics["raw_record_count"] == 3
    assert diagnostics["canonical_record_count"] == 2
    assert diagnostics["duplicate_record_count"] == 1
    assert diagnostics["duplicate_group_count"] == 1
    assert diagnostics["cross_source_duplicate_group_count"] == 1
    merged = next(item for item in records if item["canonical_id"] == "news_same")
    assert merged["source_ids"] == ["news_same"]
    assert set(merged["retrieved_by"]) == {"news_and_announcements", "rag_evidence"}
    assert merged["merged_record_count"] == 2
    assert "richer full text" in merged["text"]


def test_w09_contract_requires_external_evidence_and_internal_model_facts() -> None:
    contract = AgentDirectory().get("W09").task_contract("analyze_financial_entities")
    assert contract.upstream_input_bindings["evidence"]["required"] is True
    assert contract.upstream_input_bindings["model_facts"]["required"] is True
    assert ["EvidenceCollectionResult"] in contract.required_upstream_output_groups
    assert any("ModelPredictionResult" in group for group in contract.required_upstream_output_groups)


def test_w06_write_report_contract_does_not_accept_raw_evidence_collection() -> None:
    contract = AgentDirectory().get("W06").task_contract("write_report")
    accepted = contract.upstream_input_bindings["upstream_results"]["accepted_output_types"]
    assert "EntityAnalysisResult" in accepted
    assert "EvidenceCollectionResult" not in accepted


def _report_task() -> GraphAgentTask:
    directory = AgentDirectory()
    task_contract = directory.get("W06").task_contract("write_report")
    task = GraphAgentTask(
        task_id="T03",
        run_id="run-v181",
        session_id="session-v181",
        user_id="u",
        worker_id="W06",
        assigned_agent=REPORT_WRITER,
        objective="汇总贵州茅台分析",
        task_type="write_report",
        args={"report_goal": "汇总贵州茅台分析", "reply_language": "zh"},
        inputs={
            "upstream_results": {
                "from_task_id": "T02",
                "expected_output_type": "EntityAnalysisResult",
            }
        },
        expected_output_type="FinalReport",
        expected_output={"information_slots": ["user_facing_report", "goal_completion_summary"]},
        focus_refs=[_focus_ref()],
        completion_criteria=list(task_contract.completion_criteria),
    )
    task.completion_contract = directory.completion_contract_for_task(task)
    return task


def _analysis_dependency() -> dict[str, dict]:
    return {
        "T02": {
            "contract_version": "graph_worker_result.v1",
            "task_id": "T02",
            "agent_id": "ENTITY_ANALYST",
            "status": "completed",
            "output_type": "EntityAnalysisResult",
            "payload": {
                "entity_refs": [_focus_ref().to_dict()],
                "entity_catalog": [
                    {
                        "node_id": _focus_ref().node_id,
                        "public_code": "600519",
                        "display_label": "贵州茅台",
                    }
                ],
                "facts": [
                    {
                        "claim_id": "fact_001",
                        "statement": "贵州茅台存在一条可验证事实。",
                        "source_task_ids": ["T01"],
                    }
                ],
                "analysis": [
                    {
                        "claim_id": "analysis_001",
                        "statement": "该事实需要结合内部模型信号理解。",
                        "source_task_ids": ["T01", "T00"],
                    }
                ],
                "model_signals": [
                    {
                        "claim_id": "model_001",
                        "statement": "内部模型信号为中性。",
                        "source_task_ids": ["T00"],
                        "direction": "flat",
                        "horizon": "next_5_trading_days",
                        "strength": "slight",
                    }
                ],
                "relation_interpretations": [],
                "uncertainties": [],
                "conclusion": "外部证据与内部模型共同支持中性结论。",
                "source_task_ids": ["T01", "T00"],
                "input_diagnostics": {
                    "raw_evidence_record_count": 40,
                    "canonical_evidence_record_count": 17,
                    "duplicate_evidence_record_count": 23,
                },
            },
            "summary": "实体分析完成。",
            "confidence": 0.85,
        }
    }


class _FailingReportLLM:
    def generate_json(self, **kwargs):
        raise RuntimeError("Incomplete JSON object returned by LLM.")


class _SuccessfulReportLLM:
    def generate_json(self, **kwargs):
        request = __import__("json").loads(kwargs["messages"][1]["content"])
        contract = request["completion_contract"]
        payload = {
            "title": "贵州茅台分析",
            "sections": [
                {
                    "heading": "综合结论",
                    "markdown": "贵州茅台的外部证据与内部模型共同支持中性结论。",
                    "source_claim_ids": ["analysis_001", "model_001"],
                }
            ],
            "limitations": [],
            "completion_report": {
                "schema_version": COMPLETION_REPORT_VERSION,
                "report_source": "llm",
                "execution_status": "succeeded",
                "contract_status": "valid",
                "business_status": "sufficient",
                "completion_status": "completed",
                "expected_task_completed": True,
                "output_type": "FinalReport",
                "produced_information_slots": list(contract["required_information_slots"]),
                "missing_information_slots": [],
                "criteria": [
                    {
                        "criterion_id": item["criterion_id"],
                        "satisfied": True,
                        "reason": "终端实体分析结果足以生成报告。",
                        "source_refs": ["T02"],
                    }
                    for item in contract["criteria"]
                ],
                "limitations": [],
                "failure_kind": "none",
            },
        }
        kwargs["validator"](payload)
        return payload


def test_w06_failure_logs_exact_input_and_incomplete_json_diagnostics() -> None:
    result = run_report_writer(
        _FailingReportLLM(),
        _report_task(),
        _analysis_dependency(),
        "zh",
    )
    assert result.status == ResultStatus.FAILED
    assert result.error["code"] == "report_llm_generation_failed"
    assert result.error["incomplete_json_detected"] is True
    input_finding = next(item for item in result.findings if item["kind"] == "report_input_diagnostics")
    assert input_finding["raw_evidence_result_count"] == 0
    assert input_finding["entity_analysis_result_count"] == 1
    assert input_finding["entity_analysis_counts"]["model_signal_count"] == 1


def test_w06_success_composes_markdown_from_sections_and_logs_output() -> None:
    result = run_report_writer(
        _SuccessfulReportLLM(),
        _report_task(),
        _analysis_dependency(),
        "zh",
    )
    assert result.status == ResultStatus.COMPLETED
    assert result.data["content"].startswith("# 贵州茅台分析")
    assert "## 综合结论" in result.data["content"]
    assert result.data["used_source_claim_ids"] == ["analysis_001", "model_001"]
    output_finding = next(item for item in result.findings if item["kind"] == "report_output_diagnostics")
    assert output_finding["section_count"] == 1
    assert output_finding["markdown_composed_by_runtime"] is True


def _analysis_plan(*, include_internal: bool = True, report_uses_raw_evidence: bool = False):
    from tests.unit._forward_plan_helpers import decorate_forward_plan

    tasks = [
        {
            "task_id": "T01",
            "worker_id": "W01",
            "objective": "收集贵州茅台外部证据",
            "task_type": "collect_external_evidence",
            "args": {"collection_goal": "收集贵州茅台外部证据", "top_k": 20},
            "inputs": {},
            "constraints": [],
            "expected_output_type": "EvidenceCollectionResult",
            "priority": 1,
        }
    ]
    if include_internal:
        tasks.append(
            {
                "task_id": "T00",
                "worker_id": "W02",
                "objective": "读取贵州茅台系统内部模型事实",
                "task_type": "query_stock_prediction",
                "args": {"top_k": 10},
                "inputs": {},
                "constraints": [],
                "expected_output_type": "ModelPredictionResult",
                "priority": 1,
            }
        )
    w09_inputs = {
        "evidence": {
            "from_task_id": "T01",
            "expected_output_type": "EvidenceCollectionResult",
        }
    }
    if include_internal:
        w09_inputs["model_facts"] = {
            "from_task_id": "T00",
            "expected_output_type": "ModelPredictionResult",
        }
    tasks.append(
        {
            "task_id": "T02",
            "worker_id": "W09",
            "objective": "结合外部证据和内部模型事实分析贵州茅台",
            "task_type": "analyze_financial_entities",
            "args": {"analysis_goal": "分析贵州茅台"},
            "inputs": w09_inputs,
            "constraints": [],
            "expected_output_type": "EntityAnalysisResult",
            "priority": 2,
        }
    )
    report_refs = [
        {"from_task_id": "T02", "expected_output_type": "EntityAnalysisResult"}
    ]
    if report_uses_raw_evidence:
        report_refs.insert(
            0,
            {"from_task_id": "T01", "expected_output_type": "EvidenceCollectionResult"},
        )
    tasks.append(
        {
            "task_id": "T03",
            "worker_id": "W06",
            "objective": "汇总贵州茅台分析",
            "task_type": "write_report",
            "args": {"report_goal": "汇总贵州茅台分析"},
            "inputs": {"upstream_results": report_refs},
            "constraints": [],
            "expected_output_type": "FinalReport",
            "priority": 3,
        }
    )
    raw = {
        "goal_contract": {
            "goal_summary": "结合外部证据与系统内部模型事实分析贵州茅台并生成报告",
            "desired_output_types": ["EntityAnalysisResult", "FinalReport"],
            "required_information_slots": [
                "entity_external_evidence",
                "entity_model_signals",
                "entity_analysis",
                "user_facing_report",
            ],
            "completion_criteria": ["外部证据和内部模型事实均进入实体分析"],
            "constraints": ["不生成操作建议"],
            "access_mode": "read",
        },
        "tasks": tasks,
    }
    initial = [
        "user_request",
        "user_identity",
        "reply_language",
        "authoritative_graph_refs",
        "authoritative_financial_entities",
        "authoritative_security_entities",
        "analysis_permission",
    ]
    return decorate_forward_plan(
        raw,
        initial_slots=initial,
        goal_slots=raw["goal_contract"]["required_information_slots"],
    ), initial


def _validate_analysis_plan(plan, initial):
    from types import SimpleNamespace

    from agent.collaboration.planner import CoordinatorPlanner

    planner = CoordinatorPlanner(AgentDirectory(), llm_service=SimpleNamespace())
    runtime_values = {
        "user_id": "u",
        "reply_language": "zh",
        "focus_ref_ids": [_focus_ref().node_id],
        "context_ref_ids": [],
        "all_ref_ids": [_focus_ref().node_id],
        "as_of_time": "",
        "run_id": "run-v181",
    }
    prepared, _ = planner._prepare_payload(
        plan,
        runtime_values=runtime_values,
        authoritative_initial_information_slots=set(initial),
        request_mode="analysis",
    )
    planner._validate_payload(
        prepared,
        request_mode="analysis",
        authoritative_ref_ids={_focus_ref().node_id},
        authoritative_user_id="u",
        reply_language="zh",
        user_request="分析贵州茅台",
        authoritative_initial_information_slots=set(initial),
    )
    return prepared


def test_valid_entity_analysis_plan_uses_w01_w02_w09_and_terminal_w06_input() -> None:
    plan, initial = _analysis_plan()
    prepared = _validate_analysis_plan(plan, initial)
    tasks = {item["task_id"]: item for item in prepared["tasks"]}
    assert tasks["T02"]["inputs"]["evidence"]["from_task_id"] == "T01"
    assert tasks["T02"]["inputs"]["model_facts"]["from_task_id"] == "T00"
    assert tasks["T03"]["inputs"]["upstream_results"] == [
        {"from_task_id": "T02", "expected_output_type": "EntityAnalysisResult"}
    ]


def test_entity_analysis_plan_without_internal_result_is_rejected() -> None:
    from agent.collaboration.worker_contracts import WorkerContractViolation

    plan, initial = _analysis_plan(include_internal=False)
    try:
        _validate_analysis_plan(plan, initial)
    except WorkerContractViolation as exc:
        assert (
            "entity_model_signals" in str(exc)
            or "model_facts" in str(exc)
            or "required_upstream" in str(exc)
        )
    else:
        raise AssertionError("plan without internal model facts must be rejected")


def test_write_report_plan_with_raw_evidence_and_entity_analysis_is_rejected() -> None:
    from agent.collaboration.worker_contracts import WorkerContractViolation

    plan, initial = _analysis_plan(report_uses_raw_evidence=True)
    try:
        _validate_analysis_plan(plan, initial)
    except WorkerContractViolation as exc:
        assert "EvidenceCollectionResult" in str(exc) or "upstream_results" in str(exc)
    else:
        raise AssertionError("write_report must not consume raw evidence when EntityAnalysisResult exists")
