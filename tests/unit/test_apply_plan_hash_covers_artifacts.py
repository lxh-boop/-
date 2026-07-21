from __future__ import annotations

from strategy_apply_test_utils import apply_plan


def test_apply_plan_hash_covers_all_required_artifacts(tmp_path) -> None:
    _, _, plan = apply_plan(tmp_path)
    required = {
        "proposal_id",
        "proposal_version",
        "implementation_id",
        "implementation_hash",
        "artifact_manifest_hash",
        "diff_hash",
        "security_report_hash",
        "test_report_hash",
        "backtest_report_hash",
        "baseline_code_hash",
        "baseline_strategy_hash",
        "user_id",
        "account_id",
        "conversation_id",
        "run_id",
        "expires_at",
        "plan_hash",
    }

    assert required <= set(plan.data)
    assert all(plan.data[key] not in {"", None} for key in required)
    assert len(plan.data["plan_hash"]) == 64
