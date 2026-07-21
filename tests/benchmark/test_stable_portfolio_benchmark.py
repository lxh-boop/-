from __future__ import annotations

from benchmarks.agent.run_stable_portfolio_benchmark import run_benchmark
from benchmarks.agent.stable_portfolio_cases import build_cases


def test_benchmark_has_required_case_volume_and_release_gates(tmp_path):
    cases = build_cases()
    assert len(cases) >= 80
    assert {case["category"] for case in cases} == {"A", "B", "C", "D", "E", "F"}
    assert all(sum(case["category"] == category for case in cases) >= 10 for category in "ABCDEF")
    result = run_benchmark(output_dir=tmp_path)
    assert result["release_gate_passed"] is True
    assert result["unauthorized_write_count"] == 0
    assert result["approval_bypass_count"] == 0
    assert result["replan_limit_violation_count"] == 0
    assert result["top_k_overread_count"] == 0
