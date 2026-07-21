from strategy_position_test_utils import (
    create_position_preview,
    setup_position_account,
)


def test_position_preview_does_not_write(tmp_path) -> None:
    storage, account, positions = setup_position_account(tmp_path)
    account_before = storage.account_latest_path.read_bytes()
    positions_before = storage.positions_latest_path.read_bytes()
    orders_existed = storage.orders_path.exists()

    preview = create_position_preview(tmp_path)

    assert preview.success
    assert preview.data["not_committed"] is True
    assert storage.account_latest_path.read_bytes() == account_before
    assert storage.positions_latest_path.read_bytes() == positions_before
    assert storage.load_account("paper_u1") == account
    assert storage.load_positions("u1") == positions
    assert storage.orders_path.exists() is orders_existed
