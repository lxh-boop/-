from __future__ import annotations

from pathlib import Path

from strategy_apply_test_utils import apply_plan, apply_service


def test_apply_revalidate_detects_changed_codebase(tmp_path) -> None:
    _, _, plan = apply_plan(tmp_path)
    baseline = (
        tmp_path
        / "formal_project"
        / "portfolio"
        / "rebalance_rules.py"
    )
    with baseline.open("a", encoding="utf-8") as stream:
        stream.write("\n# changed after preview\n")

    result = apply_service(tmp_path).commit(
        user_id="u1",
        plan_id=plan.data["plan_id"],
        confirmation_token=plan.data["confirmation_token"],
        conversation_id="conv_1",
    )

    assert result.success is False
    assert "baseline_code_hash_changed" in result.errors
    assert Path(plan.data["formal_target"]).exists() is False
