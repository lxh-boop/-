from evaluation.reliability_updater import update_ai_reliability_state


def _records(score: float, count: int = 10) -> list[dict]:
    return [
        {
            "user_id": "u1",
            "evaluation_status": "evaluated",
            "adjustment_hit": 1 if score >= 0.5 else 0,
            "adjustment_alpha": 0.01 if score >= 0.5 else -0.01,
            "avoided_loss": 0.002 if score >= 0.5 else 0.0,
            "missed_gain": 0.0 if score >= 0.5 else 0.003,
            "ai_adjustment_score": score,
            "trade_date": f"2026-06-{i + 1:02d}",
        }
        for i in range(count)
    ]


def test_good_ai_adjustment_score_increases_weight_smoothly() -> None:
    state = update_ai_reliability_state(_records(0.80, count=20), "u1", old_state={"ai_reliability_weight": 0.70})

    assert state["ai_reliability_weight"] > 0.70
    assert state["ai_reliability_weight"] <= 1.0
    assert state["recent_ai_adjustment_score"] == 0.80
    assert state["status"] == "updated"


def test_bad_ai_adjustment_score_decreases_weight_smoothly() -> None:
    state = update_ai_reliability_state(_records(0.30, count=20), "u1", old_state={"ai_reliability_weight": 0.70})

    assert state["ai_reliability_weight"] < 0.70
    assert state["ai_reliability_weight"] >= 0.0
    assert state["recent_missed_gain"] > 0
    assert state["status"] == "updated"
