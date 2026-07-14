import json

from app.classic_services import load_classic_user_context, save_classic_user_context, user_output_dir
from database.repositories import UserRepository


def _form(user_id: str = "u_profile") -> dict:
    return {
        "user_id": user_id,
        "nickname": "tester",
        "initial_capital": 123456,
        "age_range": "26-35",
        "income_stability": "稳定",
        "investment_experience": "1-3年",
        "liquidity_need": "中",
        "risk_level": "C3 稳健型",
        "max_drawdown_tolerance": "15%",
        "single_loss_tolerance": "5%",
        "volatility_tolerance": "中",
        "investment_horizon": "3-6个月",
        "goal_type": "稳健增值",
        "target_return": "8%",
        "target_period": "3-6个月",
        "priority": "均衡",
        "capital_usage": "模拟学习资金",
        "preferred_industries": ["新能源"],
        "avoided_industries": ["ST股票"],
        "holding_period_preference": "中线",
        "allow_high_volatility": False,
        "trading_style": "稳健",
    }


def test_user_profile_writes_database_and_fallback_json(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"
    result = save_classic_user_context(_form(), db_path=db_path, output_dir=tmp_path / "outputs")

    assert result["status"] == "database"
    repo = UserRepository(db_path)
    profile = repo.get_user_profile("u_profile")
    assert profile["available_capital"] == 123456
    assert profile["income_stability"] == "稳定"
    assert repo.list_risk_assessments("u_profile")[-1]["risk_level"] == "C3 稳健型"
    assert repo.list_investment_goals("u_profile")[-1]["goal_type"] == "稳健增值"
    assert repo.list_trading_behaviors("u_profile")[-1]["trading_style"] == "稳健"

    fallback = user_output_dir("u_profile", tmp_path / "outputs") / "user_profile.json"
    assert json.loads(fallback.read_text(encoding="utf-8"))["nickname"] == "tester"


def test_user_profile_falls_back_when_database_unavailable(tmp_path) -> None:
    class BrokenRepository:
        def __init__(self, db_path):
            raise RuntimeError("db down")

    result = save_classic_user_context(
        _form("fallback_user"),
        db_path=tmp_path / "missing" / "db.sqlite",
        output_dir=tmp_path / "outputs",
        repository_factory=BrokenRepository,
    )

    assert result["status"] == "fallback"
    loaded = load_classic_user_context(
        "fallback_user",
        db_path=tmp_path / "missing" / "db.sqlite",
        output_dir=tmp_path / "outputs",
        repository_factory=BrokenRepository,
    )
    assert loaded["user_id"] == "fallback_user"
    assert loaded["available_capital"] == 123456
