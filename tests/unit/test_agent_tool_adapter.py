from __future__ import annotations

from pathlib import Path

import pandas as pd

import agent.tool_adapter as tools


def _write_sample_ranking(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "rank": 1,
                "date": "2026-06-05",
                "code": "1",
                "name": "测试股票A",
                "close": 10.0,
                "score": 0.99,
                "up_prob": 0.6,
                "model_name": "test_model",
                "confidence_score": 0.8,
                "confidence": "高",
                "risk_score": 0.2,
                "risk_level": "低",
            },
            {
                "rank": 2,
                "date": "2026-06-05",
                "code": "000002",
                "name": "测试股票B",
                "close": 20.0,
                "score": 0.88,
                "up_prob": 0.55,
                "model_name": "test_model",
                "confidence_score": 0.6,
                "confidence": "中",
                "risk_score": 0.5,
                "risk_level": "中",
            },
        ]
    ).to_csv(path, index=False, encoding="utf-8-sig")


def test_query_latest_ranking_success(tmp_path, monkeypatch):
    ranking_path = tmp_path / "ranking_latest.csv"
    _write_sample_ranking(ranking_path)
    monkeypatch.setattr(tools, "RANKING_LATEST_PATH", str(ranking_path))
    monkeypatch.setattr(tools, "OUTPUT_DIR", str(tmp_path))

    result = tools.tool_query_latest_ranking(topk=1)

    assert result["success"] is True
    assert len(result["records"]) == 1
    assert result["records"][0]["stock_code"] == "000001"
    assert result["trade_date"] == "2026-06-05"


def test_query_latest_ranking_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "RANKING_LATEST_PATH", str(tmp_path / "missing.csv"))
    monkeypatch.setattr(tools, "OUTPUT_DIR", str(tmp_path))

    result = tools.tool_query_latest_ranking(topk=10)

    assert result["success"] is False
    assert "未找到最新预测排名文件" in result["message"]


def test_explain_stock_by_rank_uses_fallback(tmp_path, monkeypatch):
    ranking_path = tmp_path / "ranking_latest.csv"
    _write_sample_ranking(ranking_path)
    monkeypatch.setattr(tools, "RANKING_LATEST_PATH", str(ranking_path))
    monkeypatch.setattr(tools, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(
        tools,
        "tool_query_market_context",
        lambda: {"success": False, "message": "无市场缓存"},
    )

    result = tools.tool_explain_stock("为什么排名第一")

    assert result["success"] is True
    assert "不构成投资建议" in result["explanation"]
    assert result["record"]["code"] == "000001"


def test_model_zoo_query_failure_does_not_crash(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_load_model_zoo_rows",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    result = tools.tool_query_model_zoo()

    assert "errors" in result
    assert isinstance(result["errors"], list)


def test_backtest_missing_returns_clear_message(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "BACKTEST_MASTER_TABLE_PATH", tmp_path / "missing_master.csv")
    monkeypatch.setattr(tools, "MODEL_SEARCH_RESULTS_PATH", tmp_path / "missing_search.csv")
    monkeypatch.setattr(tools, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(tools, "BACKTEST_METRICS_PATH", str(tmp_path / "missing_metrics.json"))

    result = tools.tool_query_backtest()

    assert result["success"] is False
    assert "未找到回测结果文件" in result["message"]


def test_rag_no_index_message(monkeypatch):
    monkeypatch.setattr(
        tools,
        "tool_query_rag",
        lambda question, topk=5: {
            "success": False,
            "message": "未找到 RAG 索引，请先运行 rag_indexer.py 构建索引。",
            "evidence": [],
        },
    )

    result = tools.tool_query_rag("根据研报知识库回答问题")

    assert result["success"] is False
    assert "RAG 索引" in result["message"]


def test_news_mapping_no_result_message(monkeypatch):
    monkeypatch.setattr(
        tools,
        "tool_query_news_mapping",
        lambda query: {
            "success": False,
            "message": "当前本地新闻映射库未找到明确关联股票，不能据此生成确定性结论。",
            "stocks": [],
        },
    )

    result = tools.tool_query_news_mapping("不存在的事件")

    assert result["success"] is False
    assert result["stocks"] == []
