from __future__ import annotations

from streamlit.testing.v1 import AppTest


def test_backtest_page_renders_without_running_external_api():
    at = AppTest.from_file("app.py")
    at.run(timeout=60)
    assert len(at.exception) == 0
    selectbox_labels = [box.label for box in at.selectbox]
    button_labels = [button.label for button in at.button]
    assert "回测 TopK" in selectbox_labels
    assert "检查数据并运行 T+1 回测" in button_labels
