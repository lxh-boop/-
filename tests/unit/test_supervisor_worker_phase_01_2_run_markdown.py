from __future__ import annotations

from pathlib import Path

from agent import console_trace
from agent.collaboration.models import GraphWorkerResult, ResultStatus


def _reset_trace_state() -> None:
    console_trace._RUN_FILES.clear()
    console_trace._RUN_SEQUENCE.clear()
    console_trace._RUN_FINALIZED.clear()
    console_trace.reset_flow_context()


def test_final_report_content_is_preserved_in_public_contract() -> None:
    result = GraphWorkerResult(
        task_id="W06_001",
        agent_id="REPORT_WRITER",
        status=ResultStatus.COMPLETED,
        output_type="FinalReport",
        data={
            "title": "600519分析",
            "language": "zh",
            "source_task_ids": ["W01_001"],
            "content": "这是最终面向用户的完整报告正文。",
            "limitations": [],
        },
        summary="这是最终面向用户的完整报告正文。",
    )

    public = result.safe_for_coordinator()

    assert public["data"]["content"] == "这是最终面向用户的完整报告正文。"


def test_non_report_raw_content_remains_hidden() -> None:
    result = GraphWorkerResult(
        task_id="W01_001",
        agent_id="EVIDENCE_RETRIEVER",
        status=ResultStatus.COMPLETED,
        output_type="EntityResearchResult",
        data={
            "entity_refs": [],
            "research_question": "分析对象",
            "results": [],
            "content": "不应公开的原始正文",
            "body": "不应公开的原始body",
            "full_text": "不应公开的全文",
        },
    )

    public = result.safe_for_coordinator()

    assert "content" not in public["data"]
    assert "body" not in public["data"]
    assert "full_text" not in public["data"]


def test_complete_run_markdown_contains_worker_dag_results_and_final_answer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _reset_trace_state()
    monkeypatch.setenv("AGENT_FLOW_TRACE", "1")
    monkeypatch.setenv("AGENT_FLOW_MARKDOWN_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_FLOW_TRACE_MAX_CHARS", "30000")

    run_id = "agent_run_phase_01_2_test"
    console_trace.flow_event(
        "GRAPH_REQUEST",
        {
            "raw_message": "分析600519",
            "user_id": "cht",
            "api_key": "secret-value",
        },
        run_id=run_id,
    )

    execution = {
        "success": True,
        "execution_status": "completed",
        "task_results": {
            "W01_001": {
                "task_id": "W01_001",
                "agent_id": "EVIDENCE_RETRIEVER",
                "status": "completed",
                "output_type": "EntityResearchResult",
                "summary": "实体研究完成。",
                "data": {
                    "entity_refs": [{"node_id": "object:security:600519"}],
                    "research_question": "分析600519",
                    "results": [],
                },
                "confidence": 0.85,
                "evidence_refs": [{"node_id": "evidence:test"}],
                "artifact_refs": [],
                "metadata": {
                    "duration_ms": 123.4,
                    "tool_execution": {
                        "tool_name": "graph.evidence.analyze_entities",
                        "artifact_id": "artifact_1",
                    },
                },
            },
            "W06_001": {
                "task_id": "W06_001",
                "agent_id": "REPORT_WRITER",
                "status": "completed",
                "output_type": "FinalReport",
                "summary": "完整分析报告。",
                "data": {
                    "language": "zh",
                    "source_task_ids": ["W01_001"],
                    "content": "完整分析报告。",
                    "limitations": [],
                },
                "confidence": 0.85,
                "evidence_refs": [],
                "artifact_refs": [],
                "metadata": {"duration_ms": 456.7},
            },
        },
        "graph_worker_results": {
            "items": [],
            "task_count": 2,
            "completed_count": 2,
            "failed_count": 0,
            "waiting_context_count": 0,
        },
        "execution_batches": [
            {
                "batch_index": 1,
                "task_ids": ["W01_001"],
                "agents": ["EVIDENCE_RETRIEVER"],
                "parallel": False,
            },
            {
                "batch_index": 2,
                "task_ids": ["W06_001"],
                "agents": ["REPORT_WRITER"],
                "parallel": False,
            },
        ],
        "agent_timeline": [],
        "warnings": [],
        "errors": [],
        "internal_tool_call_count": 1,
        "graph_runtime": {
            "planner": {
                "worker_selection_owner": "main_agent",
                "dag_mutation_after_planning": "forbidden",
            },
            "worker_dag": {
                "task_count": 2,
                "tasks": [
                    {
                        "task_id": "W01_001",
                        "worker_id": "W01",
                        "assigned_agent": "EVIDENCE_RETRIEVER",
                        "task_type": "analyze_entity_evidence",
                        "objective": "完成目标金融实体研究",
                        "args": {
                            "focus_ref_ids": ["object:security:600519"],
                            "research_question": "分析600519",
                        },
                        "dependency_task_ids": [],
                        "expected_output_type": "EntityResearchResult",
                        "constraints": ["read_only"],
                        "status": "ready",
                    },
                    {
                        "task_id": "W06_001",
                        "worker_id": "W06",
                        "assigned_agent": "REPORT_WRITER",
                        "task_type": "write_report",
                        "objective": "生成最终报告",
                        "args": {
                            "input_task_ids": ["W01_001"],
                            "report_goal": "回答用户问题",
                            "reply_language": "zh",
                        },
                        "dependency_task_ids": ["W01_001"],
                        "expected_output_type": "FinalReport",
                        "constraints": [],
                        "status": "created",
                    },
                ],
            },
            "focus_refs": [{"node_id": "object:security:600519"}],
        },
    }

    path = console_trace.finalize_flow_markdown(
        run_id=run_id,
        question="分析600519",
        execution=execution,
        runtime_status="completed",
        success=True,
        final_answer="完整分析报告。",
        user_id="cht",
        session_id="conv_test",
        language="zh",
        llm_runtime={
            "provider_id": "local",
            "model_name": "test-model",
            "api_key": "secret-value",
        },
    )

    content = Path(path).read_text(encoding="utf-8")

    assert "# 运行总览" in content
    assert "## MainAgent 规划信息" in content
    assert "## Worker DAG" in content
    assert "W01_001" in content
    assert "W06_001" in content
    assert "## 执行批次" in content
    assert "## Worker 执行结果" in content
    assert "私有 Tool 执行摘要" in content
    assert "graph.evidence.analyze_entities" in content
    assert "## 已解析 GraphRef" in content
    assert "## 最终回答" in content
    assert "完整分析报告。" in content
    assert "secret-value" not in content


def test_finalization_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    _reset_trace_state()
    monkeypatch.setenv("AGENT_FLOW_TRACE", "1")
    monkeypatch.setenv("AGENT_FLOW_MARKDOWN_DIR", str(tmp_path))

    kwargs = {
        "run_id": "run-idempotent",
        "question": "测试",
        "execution": {"execution_status": "completed"},
        "runtime_status": "completed",
        "success": True,
        "final_answer": "完成",
    }
    path = console_trace.finalize_flow_markdown(**kwargs)
    console_trace.finalize_flow_markdown(**kwargs)

    content = Path(path).read_text(encoding="utf-8")
    assert content.count("# 运行总览") == 1
    assert content.count("AGENT_RUN_FINAL_SNAPSHOT:run-idempotent") == 1
