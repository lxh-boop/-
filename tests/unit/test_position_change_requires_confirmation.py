from strategy_position_test_utils import (
    create_position_preview,
    position_service,
    setup_position_account,
)


def test_position_change_requires_confirmation(tmp_path) -> None:
    storage, _, positions = setup_position_account(tmp_path)
    preview = create_position_preview(tmp_path)
    result = position_service(tmp_path).commit(
        user_id="u1",
        plan_id=preview.data["plan_id"],
        confirmation_token="wrong-token",
    )

    assert preview.requires_confirmation
    assert (
        preview.data["operation_type"]
        == "confirmation_required_portfolio_operation"
    )
    assert not result.success
    assert storage.load_positions("u1") == positions
