from __future__ import annotations

import pandas as pd

from core.search.target_search import build_search_results


def test_target_search_keeps_latest_strategy_result(tmp_path, monkeypatch):
    import core.search.target_search as target_search

    model_search_dir = tmp_path / "model_search"
    model_discovery_dir = tmp_path / "model_discovery"
    backtest_dir = tmp_path / "backtests"
    model_search_dir.mkdir()
    model_discovery_dir.mkdir()
    backtest_dir.mkdir()

    candidates_path = model_discovery_dir / "model_candidates.csv"
    master_path = backtest_dir / "backtest_master_table.csv"
    results_path = model_search_dir / "search_results.csv"
    errors_path = model_search_dir / "search_errors.csv"
    report_path = model_search_dir / "model_search_report.md"

    pd.DataFrame(
        [
            {
                "model_name": "m",
                "category": "A",
                "source_url": "url",
                "has_pretrained_weight": True,
                "has_training_code": True,
                "priority": 1,
            }
        ]
    ).to_csv(candidates_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [
            {
                "run_id": "old",
                "timestamp": "20260101_000000",
                "model_name": "m",
                "topk": 10,
                "holding_days": 5,
                "rank_by": "score",
                "num_days": 60,
                "annual_return": 9.9,
                "cum_return": 1.0,
                "status": "success",
            },
            {
                "run_id": "new",
                "timestamp": "20260102_000000",
                "model_name": "m",
                "topk": 10,
                "holding_days": 5,
                "rank_by": "score",
                "num_days": 60,
                "annual_return": 0.1,
                "cum_return": 0.02,
                "status": "success",
            },
        ]
    ).to_csv(master_path, index=False, encoding="utf-8-sig")

    monkeypatch.setattr(target_search, "MODEL_SEARCH_DIR", model_search_dir)
    monkeypatch.setattr(target_search, "MODEL_CANDIDATES_PATH", candidates_path)
    monkeypatch.setattr(target_search, "BACKTEST_MASTER_TABLE_PATH", master_path)
    monkeypatch.setattr(target_search, "MODEL_SEARCH_RESULTS_PATH", results_path)
    monkeypatch.setattr(target_search, "MODEL_SEARCH_ERRORS_PATH", errors_path)
    monkeypatch.setattr(target_search, "MODEL_SEARCH_REPORT_PATH", report_path)

    results, errors = build_search_results(target_metric="annual_return", target_value=0.1, min_days=60)
    assert errors.empty
    assert results["run_id"].tolist() == ["new"]
