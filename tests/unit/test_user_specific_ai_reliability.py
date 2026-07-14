from evaluation.reliability_updater import update_ai_reliability_state


def test_ai_reliability_is_user_specific() -> None:
    records = [
        {
            "user_id": "u1",
            "evaluation_status": "evaluated",
            "adjustment_hit": 1,
            "adjustment_alpha": 0.01,
            "avoided_loss": 0.01,
            "missed_gain": 0,
            "ai_adjustment_score": 0.8,
            "trade_date": f"2026-06-{index + 1:02d}",
        }
        for index in range(20)
    ] + [
        {
            "user_id": "u2",
            "evaluation_status": "evaluated",
            "adjustment_hit": 0,
            "adjustment_alpha": -0.01,
            "avoided_loss": 0,
            "missed_gain": 0.01,
            "ai_adjustment_score": 0.2,
            "trade_date": f"2026-06-{index + 1:02d}",
        }
        for index in range(20)
    ]

    u1 = update_ai_reliability_state(records, "u1", old_state={"ai_reliability_weight": 0.70})
    u2 = update_ai_reliability_state(records, "u2", old_state={"ai_reliability_weight": 0.70})

    assert u1["ai_reliability_weight"] > 0.70
    assert u2["ai_reliability_weight"] < 0.70
    assert u1["lookback_count"] == 20
    assert u2["lookback_count"] == 20
