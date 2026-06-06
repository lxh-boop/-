from __future__ import annotations

from streamlit.testing.v1 import AppTest


def test_ai_page_renders_without_calling_api():
    at = AppTest.from_file("app.py")
    at.run(timeout=60)
    assert len(at.exception) == 0
    text_inputs = [item.label for item in at.text_input]
    buttons = [item.label for item in at.button]
    assert "AI API Key" in text_inputs
    assert "生成 Prompt" in buttons
    assert "AI 解释" in buttons
