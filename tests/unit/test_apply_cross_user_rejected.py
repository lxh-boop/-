from __future__ import annotations

from strategy_apply_test_utils import apply_plan, apply_service


def test_apply_cross_user_confirmation_is_rejected(tmp_path) -> None:
    _, _, plan = apply_plan(tmp_path)
    result = apply_service(tmp_path).commit(
        user_id="u2",
        plan_id=plan.data["plan_id"],
        confirmation_token=plan.data["confirmation_token"],
        conversation_id="conv_1",
    )

    assert result.success is False
    assert "plan_not_found" in result.errors
