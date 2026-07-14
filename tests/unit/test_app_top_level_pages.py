import importlib.util
import ast
from pathlib import Path


APP_SOURCE = Path("app.py")


def test_app_exposes_top_level_pages() -> None:
    spec = importlib.util.spec_from_file_location("streamlit_app_stage5e", Path("app.py"))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.get_app_top_level_pages() == ["首页 / 预测排名", "AI 模拟盘", "AI Agent", "系统监控"]
    assert callable(module.render_top_level_page_selector)


def test_app_uses_lazy_page_imports_for_heavy_pages() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    top_level_imports = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    imported_modules = {
        node.module
        for node in top_level_imports
        if isinstance(node, ast.ImportFrom)
    }

    assert "app.pages.model_search" not in imported_modules
    assert "app.pages.ai_agent" not in imported_modules
    assert "app.pages.system_monitor" not in imported_modules
    assert "def _get_model_search_page_renderer" in source
    assert "def _get_ai_agent_page_renderer" in source
    assert "def _get_system_monitor_page_renderer" in source


def test_app_loads_ranking_after_top_level_page_dispatch() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")
    dispatch_index = source.index("selected_top_level_page = render_top_level_page_selector()")
    ranking_index = source.index("ranking = load_ranking()", dispatch_index)

    assert dispatch_index < ranking_index
