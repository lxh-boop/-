from __future__ import annotations

from app.pages.ai_agent import (
    _collect_source_references,
    _format_preview_cell,
    _is_explainable_business_failure,
    _normalise_answer,
    _runtime_summary_from_result,
    _sandbox_rows_from_orchestration,
    _task_rows_from_orchestration,
    _tool_rows_from_result,
)
from agent.runtime import AgentRuntimeRecorder, RUN_COMPLETED, RUN_PLANNING, RUN_RUNNING


def test_ai_agent_runtime_summary_helpers_extract_traceability() -> None:
    orchestration = {
        "task_results": {
            "task_1": {
                "intent": "ranking",
                "success": True,
                "step_status": "succeeded",
                "execution_mode": "single",
                "duration_seconds": 0.12,
                "data": {"source_file": "outputs/ranking_latest.csv"},
            },
            "task_2": {
                "intent": "python_sandbox_analysis",
                "success": True,
                "step_status": "succeeded",
                "execution_mode": "single",
                "duration_seconds": 0.2,
                "data": {
                    "status": "succeeded",
                    "snapshot_id": "snap_1",
                    "code_hash": "abcdef1234567890",
                    "duration_seconds": 0.2,
                },
            },
        }
    }
    result = {
        "orchestration": orchestration,
        "tool_calls": [
            {"task_id": "task_1", "tool_name": "ranking", "success": True},
            {"task_id": "task_2", "tool_name": "python_sandbox_analysis", "success": True},
        ],
        "result": {"data": {"source_file": "outputs/ranking_latest.csv"}},
    }

    task_rows = _task_rows_from_orchestration(orchestration)
    assert task_rows[0]["task_id"] == "task_1"
    assert task_rows[1]["intent"] == "python_sandbox_analysis"

    tool_rows = _tool_rows_from_result(result)
    assert [row["tool_name"] for row in tool_rows] == ["ranking", "python_sandbox_analysis"]

    sources = _collect_source_references(result)
    assert sources[0]["source"] == "outputs/ranking_latest.csv"

    sandbox_rows = _sandbox_rows_from_orchestration(orchestration)
    assert sandbox_rows == [
        {
            "task_id": "task_2",
            "status": "succeeded",
            "snapshot_id": "snap_1",
            "code_hash": "abcdef123456",
            "duration_seconds": 0.2,
            "refusal_reason": "",
        }
    ]


def test_ai_agent_preserves_explainable_business_failure() -> None:
    result = {
        "success": False,
        "intent": "strategy_change",
        "answer": "当前描述只有长期风格倾向，缺少可执行的选股、仓位或调仓规则；请补充具体规则。",
        "result": {"errors": ["insufficient_strategy_rule"]},
    }
    answer = _normalise_answer(
        result,
        "zh",
    )
    assert _is_explainable_business_failure(result)
    assert "缺少可执行的选股" in answer
    assert "目前不能回答" not in answer


def test_ai_agent_preview_cell_formats_complex_values() -> None:
    rendered = _format_preview_cell({"changes": [{"stock_code": "000001", "quantity": 100}]})
    assert isinstance(rendered, str)
    assert '"stock_code": "000001"' in rendered


def test_ai_agent_runtime_summary_loads_persisted_snapshot(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"
    runtime = AgentRuntimeRecorder(
        user_id="u1",
        goal="runtime ui",
        db_path=db_path,
        session_id="session_1",
    )
    runtime.transition_run(RUN_PLANNING, "plan")
    runtime.transition_run(RUN_RUNNING, "run")
    runtime.create_step("task_1", "ranking")
    runtime.record_step_result(
        "task_1",
        {
            "intent": "ranking",
            "success": True,
            "message": "ranking ok",
            "data": {"records": [{"stock_code": "000001", "stock_name": "Ping An"}]},
        },
    )
    runtime.record_tool_call(
        step_id="task_1",
        tool_name="ranking",
        arguments={"top_k": 1},
        result={
            "success": True,
            "message": "ranking ok",
            "data": {"records": [{"stock_code": "000001", "stock_name": "Ping An"}]},
        },
    )
    runtime.transition_run(RUN_COMPLETED, "done")

    summary = _runtime_summary_from_result(
        {"run_id": runtime.run_id, "runtime": {"run_id": runtime.run_id, "status": "completed"}},
        db_path=str(db_path),
    )

    assert summary["run_id"] == runtime.run_id
    assert summary["status"] == "completed"
    assert summary["steps"][0]["status"] == "succeeded"
    assert summary["tool_calls"][0]["tool_name"] == "ranking"
    assert summary["sources"][0]["source_type"] == "ranking_record"
