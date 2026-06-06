from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from config import RANKING_LATEST_PATH


def test_app_loads_without_exceptions():
    at = AppTest.from_file("app.py")
    at.run(timeout=60)
    assert len(at.exception) == 0
    assert at.title[0].value.strip().endswith("A股每日股票评分系统")


def test_app_keeps_global_disclaimer():
    at = AppTest.from_file("app.py")
    at.run(timeout=60)
    warning_text = "\n".join(item.value for item in at.warning)
    assert "不构成投资建议" in warning_text


def test_app_missing_ranking_file_shows_error_without_white_screen():
    ranking_path = Path(RANKING_LATEST_PATH)
    backup_path = ranking_path.with_suffix(ranking_path.suffix + ".pytest_bak")

    if backup_path.exists():
        backup_path.unlink()
    if ranking_path.exists():
        ranking_path.rename(backup_path)

    try:
        at = AppTest.from_file("app.py")
        at.run(timeout=60)
        assert len(at.exception) == 0
        error_text = "\n".join(item.value for item in at.error)
        assert "ranking_latest.csv" in error_text
    finally:
        if backup_path.exists():
            backup_path.rename(ranking_path)
