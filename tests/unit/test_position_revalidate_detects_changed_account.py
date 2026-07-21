from dataclasses import replace

from strategy_position_test_utils import (
    create_position_preview,
    position_service,
    setup_position_account,
)


def test_position_revalidate_detects_changed_account(tmp_path) -> None:
    storage, account, _ = setup_position_account(tmp_path)
    preview = create_position_preview(tmp_path)
    storage.save_account(replace(account, cash=89900.0))
    positions_before_commit = storage.load_positions("u1")

    result = position_service(tmp_path).commit(
        user_id="u1",
        plan_id=preview.data["plan_id"],
        confirmation_token=preview.confirmation_token,
    )

    assert not result.success
    assert "account_state_changed" in result.errors
    assert storage.load_positions("u1") == positions_before_commit
