from app.classic_services import portfolio_output_dir, save_classic_user_context, user_output_dir


def test_user_id_output_paths_are_isolated(tmp_path) -> None:
    out = tmp_path / "outputs"
    u1 = user_output_dir("alice", out)
    u2 = user_output_dir("bob", out)
    p1 = portfolio_output_dir("alice", out)
    p2 = portfolio_output_dir("bob", out)

    assert u1 != u2
    assert p1 != p2
    assert str(p1).endswith("portfolio\\alice") or str(p1).endswith("portfolio/alice")


def test_user_profile_fallback_is_isolated_by_user_id(tmp_path) -> None:
    class BrokenRepository:
        def __init__(self, db_path):
            raise RuntimeError("db down")

    base = {
        "initial_capital": 1000,
        "risk_level": "C3 稳健型",
        "max_drawdown_tolerance": "15%",
        "single_loss_tolerance": "5%",
    }
    save_classic_user_context({"user_id": "alice", **base}, output_dir=tmp_path / "outputs", repository_factory=BrokenRepository)
    save_classic_user_context({"user_id": "bob", **base, "initial_capital": 2000}, output_dir=tmp_path / "outputs", repository_factory=BrokenRepository)

    assert (user_output_dir("alice", tmp_path / "outputs") / "user_profile.json").exists()
    assert (user_output_dir("bob", tmp_path / "outputs") / "user_profile.json").exists()
    assert (user_output_dir("alice", tmp_path / "outputs") / "user_profile.json").read_text(encoding="utf-8") != (
        user_output_dir("bob", tmp_path / "outputs") / "user_profile.json"
    ).read_text(encoding="utf-8")
