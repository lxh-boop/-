from __future__ import annotations

import json

from streamlit.testing.v1 import AppTest


def test_model_search_page_renders_and_can_save_strategy(tmp_path, monkeypatch):
    import app.services.model_search_results as service

    selected_path = tmp_path / "selected_strategy.json"
    monkeypatch.setattr(service, "SELECTED_STRATEGY_PATH", selected_path)
    at = AppTest.from_file("app.py")
    at.run(timeout=60)
    assert len(at.exception) == 0
    at.button(key="save_selected_strategy").click()
    at.run(timeout=60)
    assert selected_path.exists()
    data = json.loads(selected_path.read_text(encoding="utf-8"))
    assert data["model_name"]


def test_model_search_page_download_button_exists():
    at = AppTest.from_file("app.py")
    at.run(timeout=60)
    assert len(at.exception) == 0
    markdown_text = "\n".join(item.value for item in at.markdown)
    assert "目标搜索结果" in markdown_text
