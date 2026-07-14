from __future__ import annotations

from pathlib import Path

from evaluation.agent_harness.case_loader import load_cases
from evaluation.agent_harness.runner import run_harness


def test_agent_harness_loads_default_cases() -> None:
    cases = load_cases("data/evaluation/agent_harness_cases.jsonl")
    case_ids = {case.case_id for case in cases}
    assert "agent_empty_holding_news" in case_ids
    assert "agent_confirm_once" in case_ids


def test_agent_harness_runs_repeatable_confirmation_cases(tmp_path) -> None:
    cases = [
        case
        for case in load_cases("data/evaluation/agent_harness_cases.jsonl")
        if case.case_id in {"agent_preview_no_execute", "agent_confirm_once"}
    ]

    first = run_harness(cases, output_dir=tmp_path / "run_1", export=True)
    second = run_harness(cases, output_dir=tmp_path / "run_2", export=True)

    assert first["metrics"]["case_pass_rate"] == 1.0
    assert second["metrics"]["case_pass_rate"] == 1.0
    assert Path(first["report_path"]).exists()
    assert Path(second["report_path"]).exists()
    confirm_result = next(item for item in second["results"] if item["case"]["case_id"] == "agent_confirm_once")
    assert any(
        assertion["name"] == "duplicate_confirmation_safe" and assertion["passed"]
        for assertion in confirm_result["assertions"]
    )
