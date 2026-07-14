from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

from database.connection import get_connection, initialize_database
from database.repositories import SystemMonitorRepository
from evaluation import system_monitor
from evaluation.system_monitor import (
    build_system_monitor_snapshot,
    collect_and_store_system_monitor_snapshot,
    list_system_monitor_alerts,
    list_system_monitor_history,
)


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def _insert_fixture_rows(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO news_event(news_id, title, source, publish_time, trade_date, event_type, content_level)
            VALUES
            ('news_1', '公司订单增长', 'sample', '2026-06-30 09:00:00', '2026-07-01', 'earnings', 'full_text'),
            ('news_2', '行业景气观察', 'sample', '2026-06-30 10:00:00', '2026-07-01', 'industry', 'title_only')
            """
        )
        conn.execute(
            """
            INSERT INTO news_chunk(
                chunk_id, news_id, chunk_index, chunk_text, source, publish_time, trade_date, stock_code, content_level
            )
            VALUES
            ('chunk_1', 'news_1', 0, '公司订单增长，产能利用率改善。', 'sample', '2026-06-30 09:00:00', '2026-07-01', '000001', 'full_text'),
            ('chunk_2', 'news_2', 0, '行业景气度观察。', 'sample', '2026-06-30 10:00:00', '2026-07-01', '000002', 'title_only')
            """
        )
        conn.execute(
            """
            INSERT INTO rag_retrieval_log(
                retrieval_id, query, query_type, user_id, stock_code, trade_date,
                bm25_results, dense_results, selected_chunk_ids, returned_chunk_ids
            )
            VALUES
            ('retrieval_1', '订单增长影响', 'stock_news', 'u1', '000001', '2026-07-01',
             '["chunk_1"]', '["chunk_1"]', '["chunk_1"]', '["chunk_1"]')
            """
        )
        conn.execute(
            """
            INSERT INTO agent_runs(run_id, user_id, goal, status, started_at, finished_at, metadata_json)
            VALUES
            ('run_1', 'u1', '查看组合', 'completed', '2026-07-01 09:00:00', '2026-07-01 09:00:03', '{"replan_count": 1}'),
            ('run_2', 'u1', '检查新闻', 'failed', '2026-07-01 10:00:00', '2026-07-01 10:00:05', '{}')
            """
        )
        conn.execute(
            """
            INSERT INTO agent_steps(step_id, run_id, intent, status, tool_name, started_at, finished_at)
            VALUES
            ('step_1', 'run_1', 'portfolio_state', 'completed', 'portfolio_state', '2026-07-01 09:00:00', '2026-07-01 09:00:01')
            """
        )
        conn.execute(
            """
            INSERT INTO agent_tool_calls(tool_call_id, run_id, step_id, user_id, tool_name, status, started_at, finished_at)
            VALUES
            ('tool_1', 'run_1', 'step_1', 'u1', 'portfolio_state', 'completed', '2026-07-01 09:00:00', '2026-07-01 09:00:01')
            """
        )
        conn.execute(
            """
            INSERT INTO agent_sources(source_id, run_id, user_id, source_type, source_title, retrieved_at)
            VALUES('source_1', 'run_1', 'u1', 'db', 'paper_account_snapshot', '2026-07-01 09:00:01')
            """
        )
        conn.execute(
            """
            INSERT INTO paper_nav_history(
                nav_id, user_id, account_id, trade_date, cash, position_market_value,
                total_assets, cumulative_return, time_weighted_return, drawdown
            )
            VALUES
            ('nav_1', 'u1', 'acct_1', '2026-06-30', 50000, 50000, 100000, 0.0, 0.0, 0.0),
            ('nav_2', 'u1', 'acct_1', '2026-07-01', 30000, 70000, 100000, 0.02, 0.02, -0.03)
            """
        )
        conn.execute(
            """
            INSERT INTO paper_account_snapshot(snapshot_id, user_id, account_id, trade_date, cash, position_market_value, total_assets)
            VALUES('snap_1', 'u1', 'acct_1', '2026-07-01', 30000, 70000, 100000)
            """
        )
        conn.execute(
            """
            INSERT INTO portfolio_position(
                position_id, user_id, asset_code, asset_name, asset_type, quantity, current_price, market_value, industry
            )
            VALUES
            ('pos_1', 'u1', '000001', '平安银行', 'stock', 1000, 40, 40000, '银行'),
            ('pos_2', 'u1', '000002', '万科A', 'stock', 1000, 30, 30000, '地产')
            """
        )
        conn.execute(
            """
            INSERT INTO paper_order(order_id, user_id, account_id, trade_date, stock_code, action, gross_amount, total_fee)
            VALUES('order_1', 'u1', 'acct_1', '2026-07-01', '000001', 'buy', 10000, 3)
            """
        )
        conn.execute(
            """
            INSERT INTO agent_decision_log(
                decision_id, user_id, trade_date, stock_code, original_pred_score, news_adjustment, user_constraint
            )
            VALUES('decision_1', 'u1', '2026-07-01', '000001', 0.5, '0.10', '{"position_adjustment_ratio": 0.9}')
            """
        )
        conn.commit()


def _prepare_monitor_fixture(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    db_path = tmp_path / "agent_quant.db"
    output_dir = tmp_path / "outputs"
    data_dir = tmp_path / "data"
    initialize_database(db_path)
    _insert_fixture_rows(db_path)
    _write_csv(
        output_dir / "ranking_latest.csv",
        [
            {"code": "000001", "pred_score": 0.8, "prediction_date": "2026-07-01", "model_name": "zoo:chronos_bolt_small", "industry": "银行"},
            {"code": "000002", "pred_score": 0.6, "prediction_date": "2026-07-01", "model_name": "zoo:chronos_bolt_small", "industry": "地产"},
        ],
    )
    _write_csv(
        data_dir / "latest_raw_stock_data.csv",
        [
            {"code": "000001", "date": "2026-07-01", "close": 40},
            {"code": "000002", "date": "2026-07-01", "close": 30},
        ],
    )
    _write_csv(
        data_dir / "latest_feature_stock_data_alpha158.csv",
        [
            {"code": "000001", "date": "2026-06-30", "alpha_001": 1.0, "alpha_002": 2.0},
            {"code": "000002", "date": "2026-06-30", "alpha_001": 2.0, "alpha_002": 3.0},
            {"code": "000001", "date": "2026-07-01", "alpha_001": 1.5, "alpha_002": 2.5},
            {"code": "000002", "date": "2026-07-01", "alpha_001": 2.5, "alpha_002": 3.5},
        ],
    )
    (output_dir / "backtest_metrics.json").write_text(
        json.dumps({"benchmark_return": 0.01, "information_ratio": 0.5}, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_csv(
        output_dir / "backtest_trades.csv",
        [
            {"trade_date": "2026-06-30", "stock_code": "000001"},
            {"trade_date": "2026-07-01", "stock_code": "000002"},
        ],
    )
    thresholds_path = tmp_path / "thresholds.json"
    thresholds_path.write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "rule_id": "portfolio_single_stock_concentration_high",
                        "layer": "portfolio",
                        "metric": "single_stock_concentration",
                        "operator": "max",
                        "warning": 0.25,
                        "critical": 0.3,
                        "message": "Single-stock concentration is high.",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(system_monitor, "LATEST_RAW_DATA_PATH", str(data_dir / "latest_raw_stock_data.csv"))
    monkeypatch.setattr(system_monitor, "LATEST_FEATURE_DATA_PATH", str(data_dir / "latest_feature_stock_data_alpha158.csv"))
    monkeypatch.setattr(system_monitor, "BACKTEST_METRICS_PATH", str(output_dir / "backtest_metrics.json"))
    monkeypatch.setattr(system_monitor, "BACKTEST_TRADES_PATH", str(output_dir / "backtest_trades.csv"))
    return db_path, output_dir, thresholds_path


def _count_rows(db_path: Path, table: str) -> int:
    with get_connection(db_path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_system_monitor_migration_and_repository_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "agent_quant.db"
    initialize_database(db_path)

    repo = SystemMonitorRepository(db_path)
    repo.upsert_snapshot(
        {
            "snapshot_id": "snapshot_1",
            "trade_date": "2026-07-01",
            "user_id": "u1",
            "overall_status": "normal",
            "data_metrics": {"stock_coverage": 1.0},
            "model_metrics": {},
            "rag_metrics": {},
            "agent_metrics": {},
            "portfolio_metrics": {},
            "version_info": {},
            "missing_modules": [],
        }
    )

    stored = repo.get_snapshot("snapshot_1")
    assert stored is not None
    assert stored["data_metrics"]["stock_coverage"] == 1.0
    assert stored["missing_modules"] == []


def test_system_monitor_collects_layers_and_persists_only_monitor_tables(tmp_path: Path, monkeypatch) -> None:
    db_path, output_dir, thresholds_path = _prepare_monitor_fixture(tmp_path, monkeypatch)
    protected_counts = {
        table: _count_rows(db_path, table)
        for table in ["paper_order", "paper_nav_history", "portfolio_position", "agent_decision_log"]
    }

    result = collect_and_store_system_monitor_snapshot(
        db_path=db_path,
        user_id="u1",
        output_dir=output_dir,
        thresholds_path=thresholds_path,
    )

    assert result.snapshot["snapshot_id"] == "system_monitor_u1_20260701"
    assert result.snapshot["overall_status"] == "critical"
    assert result.snapshot["data_metrics"]["ranking_stock_count"] == 2
    assert result.snapshot["model_metrics"]["model_names"] == ["zoo:chronos_bolt_small"]
    assert result.snapshot["rag_metrics"]["rag_query_count"] == 1
    assert result.snapshot["agent_metrics"]["agent_run_count"] == 2
    assert result.snapshot["portfolio_metrics"]["single_stock_concentration"] == 0.4
    assert any(alert["metric_name"] == "single_stock_concentration" for alert in result.alerts)
    assert _count_rows(db_path, "system_monitor_snapshots") == 1
    assert _count_rows(db_path, "system_monitor_alerts") == 1
    assert protected_counts == {
        table: _count_rows(db_path, table)
        for table in ["paper_order", "paper_nav_history", "portfolio_position", "agent_decision_log"]
    }


def test_system_monitor_snapshot_is_idempotent_per_user_and_trade_date(tmp_path: Path, monkeypatch) -> None:
    db_path, output_dir, thresholds_path = _prepare_monitor_fixture(tmp_path, monkeypatch)

    collect_and_store_system_monitor_snapshot(
        db_path=db_path,
        user_id="u1",
        output_dir=output_dir,
        thresholds_path=thresholds_path,
    )
    collect_and_store_system_monitor_snapshot(
        db_path=db_path,
        user_id="u1",
        output_dir=output_dir,
        thresholds_path=thresholds_path,
    )

    assert _count_rows(db_path, "system_monitor_snapshots") == 1
    assert len(list_system_monitor_history(db_path=db_path, user_id="u1")) == 1
    assert len(list_system_monitor_alerts(db_path=db_path, user_id="u1")) == 1


def test_system_monitor_handles_missing_optional_modules(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "agent_quant.db"
    output_dir = tmp_path / "outputs"
    data_dir = tmp_path / "data"
    initialize_database(db_path)
    monkeypatch.setattr(system_monitor, "LATEST_RAW_DATA_PATH", str(data_dir / "missing_raw.csv"))
    monkeypatch.setattr(system_monitor, "LATEST_FEATURE_DATA_PATH", str(data_dir / "missing_features.csv"))
    monkeypatch.setattr(system_monitor, "BACKTEST_METRICS_PATH", str(output_dir / "missing_metrics.json"))
    monkeypatch.setattr(system_monitor, "BACKTEST_TRADES_PATH", str(output_dir / "missing_trades.csv"))

    result = build_system_monitor_snapshot(db_path=db_path, user_id="u1", output_dir=output_dir)

    assert result.snapshot["data_metrics"]["ranking_stock_count"] == 0
    assert "data:ranking_latest.csv" in result.snapshot["missing_modules"]
    assert "rag:rag_index" in result.snapshot["missing_modules"]
