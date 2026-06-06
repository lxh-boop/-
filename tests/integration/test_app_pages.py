from __future__ import annotations

from streamlit.testing.v1 import AppTest


def test_all_main_tabs_render():
    at = AppTest.from_file("app.py")
    at.run(timeout=60)
    labels = [tab.label for tab in at.tabs]
    assert "首页 / 预测排名" in labels
    assert "模型搜索与回测" in labels
    assert "回测分析" in labels
    assert "AI 解释" in labels
    assert "系统设置" in labels


def test_sidebar_controls_exist():
    at = AppTest.from_file("app.py")
    at.run(timeout=60)
    selectbox_labels = [box.label for box in at.selectbox]
    button_labels = [button.label for button in at.button]
    assert "选择展示 TopK" in selectbox_labels
    assert "选择模型" in selectbox_labels
    assert "验证 AI" in button_labels
    assert "每日更新并生成预测排名" in button_labels
