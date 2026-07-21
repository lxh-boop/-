"""Offline, reproducible benchmark cases for the stable-portfolio workflow."""

from __future__ import annotations

from typing import Any


CATEGORY_NAMES = {
    "A": "intent_and_top_k",
    "B": "single_position_constraint",
    "C": "industry_constraint",
    "D": "readonly_replan",
    "E": "terminal_and_write_safety",
    "F": "final_response_contract",
}


def build_cases() -> list[dict[str, Any]]:
    """Build 84 declarative cases: 14 cases for each required category."""

    cases: list[dict[str, Any]] = []
    for category, name in CATEGORY_NAMES.items():
        for number in range(1, 15):
            target_count = 3 + (number % 8)
            case = {
                "case_id": f"{category}{number:02d}",
                "category": category,
                "category_name": name,
                "target_position_count": target_count,
                "execution_mode": "offline_llm_contract" if number <= 4 else "deterministic",
                "repeat_count": 5 if number <= 4 else 3,
            }
            if category == "A":
                case.update({"kind": "top_k", "expected_top_k": target_count * 2})
            elif category == "B":
                case.update({"kind": "single_limit", "max_single_weight": 0.08, "observed_weight": 0.20 + number / 100})
            elif category == "C":
                case.update({"kind": "industry_unknown", "max_industry_weight": 0.30})
            elif category == "D":
                case.update({"kind": "readonly_replan", "replan_limit": 2})
            elif category == "E":
                case.update({"kind": "terminal_safety", "expected_action": "report_limitation"})
            else:
                case.update({"kind": "final_response", "expected_message_type": "FINAL_RESPONSE"})
            cases.append(case)
    return cases

