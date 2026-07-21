from __future__ import annotations

import json
from collections import Counter

from benchmarks.agent_capability.case_dataset import build_cases, ensure_case_files
from benchmarks.agent_capability.scoring import aggregate_metrics, score_trace


def test_l1_dataset_is_balanced_and_split_as_specified(tmp_path):
    cases = build_cases()
    assert len(cases) == 180
    assert Counter(case["category_code"] for case in cases) == {code: 30 for code in "ABCDEF"}
    assert Counter(case["split"] for case in cases) == {"development": 108, "validation": 36, "hidden": 36}

    paths = ensure_case_files(tmp_path)
    hidden_row = json.loads(paths["hidden"].read_text(encoding="utf-8").splitlines()[0])
    assert "gold" not in hidden_row
    assert paths["hidden_gold"].exists()


def test_l1_score_requires_real_llm_and_detects_write():
    case = next(case for case in build_cases() if case["category_code"] == "F")
    trace = {
        "real_llm": False,
        "runtime_status": "completed",
        "state_changed": True,
        "tool_names": ["paper_order"],
        "tool_arguments": [{}],
        "user_goal": {},
        "task_plan": {},
        "stages": {},
        "duration_seconds": 1.0,
        "answer": "completed",
        "orchestration": {},
        "final_response_audit": {},
    }
    score = score_trace(case, case["gold"], trace)
    assert not score["success"]
    assert score["security"]["unauthorized_write"] == 1.0
    assert aggregate_metrics([{"case_id": case["case_id"], "score": score}])["unauthorized_write_rate"] == 1.0
