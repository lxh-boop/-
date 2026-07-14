from __future__ import annotations

import importlib
from pathlib import Path

from skills.base import REQUIRED_SKILL_MD_SECTIONS
from skills.schemas import CORE_QUESTIONS


SKILL_NAMES = [
    "news_event_extraction",
    "news_stock_mapping",
    "news_impact_scoring",
    "kline_prediction_interpretation",
    "signal_fusion",
    "user_profile_adaptation",
    "paper_trading_rebalance",
    "recommendation_explanation",
    "compliance_risk_control",
]


def test_all_skill_docs_exist_and_have_required_sections() -> None:
    root = Path("skills")

    for skill_name in SKILL_NAMES:
        skill_md = root / skill_name / "SKILL.md"
        assert skill_md.exists(), f"missing {skill_md}"

        text = skill_md.read_text(encoding="utf-8")
        for section in REQUIRED_SKILL_MD_SECTIONS:
            assert f"## {section}" in text, f"{skill_name} missing section {section}"


def test_skill_docs_cover_core_database_questions() -> None:
    for skill_name in SKILL_NAMES:
        text = (Path("skills") / skill_name / "SKILL.md").read_text(encoding="utf-8")
        for question in CORE_QUESTIONS:
            assert question in text, f"{skill_name} does not mention {question}"


def test_skill_schema_modules_import() -> None:
    for skill_name in SKILL_NAMES:
        module = importlib.import_module(f"skills.{skill_name}.schema")
        exported_classes = [name for name in dir(module) if name.endswith(("Input", "Output"))]
        assert exported_classes, f"{skill_name} schema has no input/output dataclasses"
