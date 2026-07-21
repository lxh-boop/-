from strategy_position_test_utils import (
    create_position_preview,
    position_service,
    setup_position_account,
)


def test_position_execution_preserves_before_snapshot(tmp_path) -> None:
    storage, _, positions = setup_position_account(tmp_path)
    preview = create_position_preview(tmp_path)
    result = position_service(tmp_path).commit(
        user_id="u1",
        plan_id=preview.data["plan_id"],
        confirmation_token=preview.confirmation_token,
    )

    assert result.success
    history = storage.list_strategy_execution_history(
        "u1",
        "paper_u1",
    )
    assert history
    assert history[-1]["positions_before"][0]["quantity"] == (
        positions[0].quantity
    )
    assert history[-1]["positions_after"]
    assert history[-1]["cash_before"] == 90000.0
    assert history[-1]["cash_after"] != 90000.0
