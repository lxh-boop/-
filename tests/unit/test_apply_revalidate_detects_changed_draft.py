from __future__ import annotations

from pathlib import Path

from strategy_apply_test_utils import apply_plan, apply_service


def test_apply_revalidate_detects_changed_draft(tmp_path) -> None:
    _, implementation, plan = apply_plan(tmp_path)
    root = Path(implementation.data["artifact_root"])
    with (root / "diff.patch").open("a", encoding="utf-8") as stream:
        stream.write("# tampered\n")

    result = apply_service(tmp_path).commit(
        user_id="u1",
        plan_id=plan.data["plan_id"],
        confirmation_token=plan.data["confirmation_token"],
        conversation_id="conv_1",
    )

    assert result.success is False
    assert "diff_hash_changed" in result.errors
    assert Path(plan.data["formal_target"]).exists() is False
