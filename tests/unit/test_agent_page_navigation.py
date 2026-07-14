from __future__ import annotations

import importlib.util
from pathlib import Path


def test_agent_page_is_top_level_navigation() -> None:
    spec = importlib.util.spec_from_file_location("streamlit_app_stage5j", Path("app.py"))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.get_app_top_level_pages() == ["首页 / 预测排名", "AI 模拟盘", "AI Agent", "系统监控"]
    assert callable(module.render_top_level_page_selector)
