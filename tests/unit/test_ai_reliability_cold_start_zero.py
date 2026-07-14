import json

from evaluation.evaluation_store import load_ai_reliability_state
from evaluation.reliability_updater import update_ai_reliability_state


def test_cold_start_ai_reliability_is_zero(tmp_path) -> None:
    state = load_ai_reliability_state("u1", output_dir=tmp_path / "outputs")

    assert state["ai_reliability_weight"] == 0.0
    assert state["status"] == "cold_start"


def test_less_than_minimum_history_keeps_reliability_zero() -> None:
    records = [
        {"user_id": "u1", "evaluation_status": "evaluated", "ai_adjustment_score": 0.9, "adjustment_hit": 1}
        for _ in range(19)
    ]
    state = update_ai_reliability_state(records, "u1", old_state={"ai_reliability_weight": 0.8})

    assert state["ai_reliability_weight"] == 0.0
    assert state["lookback_count"] == 19
    assert state["status"] == "cold_start"


def test_legacy_cold_start_state_with_old_weight_is_normalized(tmp_path) -> None:
    state_path = tmp_path / "outputs" / "evaluation" / "ai_reliability_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "u1": {
                    "user_id": "u1",
                    "ai_reliability_weight": 0.70,
                    "lookback_count": 0,
                    "status": "cold_start",
                }
            }
        ),
        encoding="utf-8",
    )

    state = load_ai_reliability_state("u1", output_dir=tmp_path / "outputs")

    assert state["ai_reliability_weight"] == 0.0
    assert state["status"] == "cold_start"
