from __future__ import annotations

import time
from pathlib import Path

from agent.orchestration import multi_task_executor as mte


def _successful_tool(intent: str, arguments: dict, **_: object) -> dict:
    return {
        "success": True,
        "message": f"{intent} ok",
        "data": {"intent": intent, "arguments": arguments},
        "warnings": [],
        "errors": [],
        "tool_name": intent,
    }


def test_independent_read_only_tasks_run_concurrently(monkeypatch, tmp_path: Path) -> None:
    def slow_execute(intent: str, arguments: dict, **kwargs: object) -> dict:
        time.sleep(0.45)
        return _successful_tool(intent, arguments, **kwargs)

    monkeypatch.setattr(mte, "_execute_single", slow_execute)
    decomposition = {
        "tasks": [
            {"task_id": "task_1", "intent": "ranking", "parameters": {}, "depends_on": []},
            {"task_id": "task_2", "intent": "report", "parameters": {}, "depends_on": []},
        ]
    }

    started = time.perf_counter()
    result = mte.execute_multi_intent_plan(
        decomposition,
        user_id="u1",
        output_dir=tmp_path,
        default_top_k=5,
        context={"max_concurrent_reads": 2},
    )
    elapsed = time.perf_counter() - started

    assert result["success"] is True
    assert elapsed < 0.75
    assert result["execution_batches"] == [["task_1", "task_2"]]
    assert result["task_results"]["task_1"]["step_status"] == "succeeded"
    assert result["task_results"]["task_2"]["step_status"] == "succeeded"


def test_dependent_tasks_wait_for_previous_result(monkeypatch, tmp_path: Path) -> None:
    started_intents: list[str] = []

    def ordered_execute(intent: str, arguments: dict, **kwargs: object) -> dict:
        started_intents.append(intent)
        time.sleep(0.05)
        return _successful_tool(intent, arguments, **kwargs)

    monkeypatch.setattr(mte, "_execute_single", ordered_execute)
    decomposition = {
        "tasks": [
            {"task_id": "task_1", "intent": "ranking", "parameters": {}, "depends_on": []},
            {"task_id": "task_2", "intent": "report", "parameters": {}, "depends_on": ["task_1"]},
        ]
    }

    result = mte.execute_multi_intent_plan(
        decomposition,
        user_id="u1",
        output_dir=tmp_path,
        default_top_k=5,
        context={"max_concurrent_reads": 2},
    )

    assert result["success"] is True
    assert result["execution_batches"] == [["task_1"], ["task_2"]]
    assert started_intents == ["ranking", "report"]


def test_dependent_stock_analysis_uses_ranking_records(monkeypatch, tmp_path: Path) -> None:
    analysed_codes: list[str] = []

    def execute_with_ranking(intent: str, arguments: dict, **kwargs: object) -> dict:
        if intent == "ranking":
            return {
                "success": True,
                "message": "ranking ok",
                "data": {
                    "records": [
                        {"stock_code": "000001", "stock_name": "One"},
                        {"stock_code": "000002", "stock_name": "Two"},
                    ]
                },
                "warnings": [],
                "errors": [],
                "tool_name": intent,
            }
        if intent == "stock_analysis":
            analysed_codes.append(str(arguments.get("stock_code") or ""))
            return _successful_tool(intent, arguments, **kwargs)
        return _successful_tool(intent, arguments, **kwargs)

    monkeypatch.setattr(mte, "_execute_single", execute_with_ranking)
    decomposition = {
        "tasks": [
            {"task_id": "task_1", "intent": "ranking", "parameters": {}, "depends_on": []},
            {"task_id": "task_2", "intent": "stock_analysis", "parameters": {}, "depends_on": ["task_1"]},
        ]
    }

    result = mte.execute_multi_intent_plan(
        decomposition,
        user_id="u1",
        output_dir=tmp_path,
        default_top_k=5,
        context={"max_concurrent_reads": 2},
    )

    assert result["success"] is True
    assert result["task_results"]["task_2"]["execution_mode"] == "foreach"
    assert analysed_codes == ["000001", "000002"]


def test_protected_multi_intent_is_rejected_before_execution(monkeypatch, tmp_path: Path) -> None:
    called = False

    def fail_if_called(intent: str, arguments: dict, **kwargs: object) -> dict:
        nonlocal called
        called = True
        return _successful_tool(intent, arguments, **kwargs)

    monkeypatch.setattr(mte, "_execute_single", fail_if_called)
    decomposition = {
        "tasks": [
            {
                "task_id": "task_1",
                "intent": "preview_add_stock",
                "parameters": {"stock_code": "600519"},
                "depends_on": [],
            }
        ]
    }

    result = mte.execute_multi_intent_plan(
        decomposition,
        user_id="u1",
        output_dir=tmp_path,
    )

    assert result["success"] is False
    assert result["execution_status"] == "rejected"
    assert "protected_multi_intent_requires_separate_confirmation:preview_add_stock" in result["errors"]
    assert called is False


def test_empty_dependency_gets_terminal_replan_skip(monkeypatch, tmp_path: Path) -> None:
    def execute_empty_portfolio(intent: str, arguments: dict, **kwargs: object) -> dict:
        if intent == "portfolio_state":
            return {
                "success": True,
                "message": "empty portfolio",
                "data": {"position_count": 0, "positions": []},
                "warnings": [],
                "errors": [],
                "tool_name": intent,
            }
        return _successful_tool(intent, arguments, **kwargs)

    monkeypatch.setattr(mte, "_execute_single", execute_empty_portfolio)
    decomposition = {
        "tasks": [
            {"task_id": "task_1", "intent": "portfolio_state", "parameters": {}, "depends_on": []},
            {"task_id": "task_2", "intent": "stock_news", "parameters": {}, "depends_on": ["task_1"]},
        ]
    }

    result = mte.execute_multi_intent_plan(
        decomposition,
        user_id="u1",
        output_dir=tmp_path,
    )

    assert result["success"] is True
    assert result["execution_status"] == "partially_completed"
    assert result["replan_count"] == 0
    assert result["task_results"]["task_2"]["step_status"] == "skipped"
    assert result["task_results"]["task_2"]["execution_mode"] == "terminal_replan_skip"
    assert result["errors"] == []


def test_empty_stock_rag_replans_once_to_stock_news(monkeypatch, tmp_path: Path) -> None:
    executed: list[str] = []

    def execute_rag_then_news(intent: str, arguments: dict, **kwargs: object) -> dict:
        executed.append(intent)
        if intent == "stock_rag":
            return {
                "success": True,
                "message": "no chunks",
                "data": {"stock_code": arguments.get("stock_code"), "chunks": [], "status": "no_rag_chunks"},
                "warnings": [],
                "errors": [],
                "tool_name": intent,
            }
        if intent == "stock_news":
            return {
                "success": True,
                "message": "news ok",
                "data": {"stock_code": arguments.get("stock_code"), "events": [{"title": "example"}]},
                "warnings": [],
                "errors": [],
                "tool_name": intent,
            }
        return _successful_tool(intent, arguments, **kwargs)

    monkeypatch.setattr(mte, "_execute_single", execute_rag_then_news)
    decomposition = {
        "tasks": [
            {
                "task_id": "task_1",
                "intent": "stock_rag",
                "parameters": {"stock_code": "000001", "query": "risk"},
                "depends_on": [],
            }
        ]
    }

    result = mte.execute_multi_intent_plan(
        decomposition,
        user_id="u1",
        output_dir=tmp_path,
    )

    assert result["success"] is True
    assert result["replan_count"] == 1
    assert result["replan_limits"] == {"max_rounds": 2, "max_new_steps": 5}
    assert result["execution_batches"] == [["task_1"], ["replan_1_stock_news"]]
    assert executed == ["stock_rag", "stock_news"]
    assert result["task_results"]["replan_1_stock_news"]["step_status"] == "succeeded"
