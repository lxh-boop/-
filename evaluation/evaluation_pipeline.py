from __future__ import annotations

from pathlib import Path
from typing import Any

from evaluation.ai_adjustment_evaluator import evaluate_due_adjustments as _evaluate_due_adjustments
from evaluation.evaluation_store import (
    append_ai_adjustment_evaluations,
    load_ai_adjustment_evaluations,
    load_ai_reliability_state,
    save_ai_reliability_state,
)
from evaluation.reliability_updater import update_ai_reliability_state as _update_ai_reliability_state


def evaluate_due_adjustments(
    records: list[dict[str, Any]] | None = None,
    as_of_date: str | None = None,
    output_dir: str | Path = "outputs",
    persist: bool = True,
) -> dict[str, Any]:
    source = records if records is not None else load_ai_adjustment_evaluations(output_dir)
    result = _evaluate_due_adjustments(source, as_of_date=as_of_date)
    if persist:
        append_ai_adjustment_evaluations(result["evaluations"], output_dir=output_dir)
    return result


def update_ai_reliability(
    user_id: str,
    as_of_date: str = "",
    output_dir: str | Path = "outputs",
) -> dict[str, Any]:
    records = load_ai_adjustment_evaluations(output_dir)
    old_state = load_ai_reliability_state(user_id, output_dir)
    state = _update_ai_reliability_state(records, user_id=user_id, old_state=old_state, as_of_date=as_of_date)
    save_ai_reliability_state(state, output_dir)
    return state
