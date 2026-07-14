from app.classic_services import get_classic_user_profile_form_options


def test_classic_user_profile_form_options_exist() -> None:
    options = get_classic_user_profile_form_options()

    assert options["age_range"] == ["18-25", "26-35", "36-45", "46-60", "60以上"]
    assert options["income_stability"] == ["不稳定", "一般", "较稳定", "稳定"]
    assert "C3 稳健型" in options["risk_level"]
    assert options["max_drawdown_tolerance"] == ["5%", "10%", "15%", "20%", "30%以上"]
    assert "新能源" in options["preferred_industries"]
    assert "ST股票" in options["avoided_industries"]
    assert options["trading_style"] == ["保守", "稳健", "积极", "激进"]
