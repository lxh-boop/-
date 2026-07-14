from pathlib import Path


def test_stage5b_frontend_page_files_are_removed() -> None:
    root = Path("app/pages")
    removed = [
        "dashboard.py",
        "recommendations.py",
        "portfolio.py",
        "risk_monitor.py",
        "pipeline_runner.py",
        "reports.py",
        "model_monitor.py",
        "settings.py",
        "page_loaders.py",
        "streamlit_stub.py",
    ]

    for name in removed:
        assert not (root / name).exists()


def test_backend_agent_and_pipeline_files_are_kept() -> None:
    kept = [
        "database",
        "rag",
        "scoring",
        "portfolio",
        "pipelines",
        "skills",
        "agent/pipeline_tool.py",
        "agent/recommendation_tool.py",
        "agent/portfolio_tool.py",
        "agent/rag_tool.py",
        "agent/report_tool.py",
        "agent/decision_log_tool.py",
        "agent/agent_registry.py",
    ]

    for path in kept:
        assert Path(path).exists()


def test_allowed_classic_pages_are_kept() -> None:
    assert Path("app/pages/model_search.py").exists()
    assert Path("app/pages/ai_agent.py").exists()
    assert Path("app/pages/ai_paper_trading.py").exists()
    assert Path("app/pages/__init__.py").exists()
