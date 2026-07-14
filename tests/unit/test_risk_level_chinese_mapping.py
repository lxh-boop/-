from app.display_labels import action_label, risk_level_label


def test_risk_level_chinese_mapping() -> None:
    assert risk_level_label("low") == "低风险"
    assert risk_level_label("medium") == "中等风险"
    assert risk_level_label("high") == "高风险"
    assert risk_level_label("very_high") == "极高风险"
    assert risk_level_label("unknown") == "未知"


def test_action_chinese_mapping() -> None:
    assert action_label("paper_buy") == "买入"
    assert action_label("paper_sell") == "卖出"
    assert action_label("paper_reduce") == "减仓"
    assert action_label("paper_hold") == "未交易"
    assert action_label("keep") == "keep"
    assert action_label("down_weight") == "down_weight"
    assert action_label("hold") == "hold"
    assert action_label("risk_alert") == "risk_alert"
    assert action_label("exclude") == "exclude"
