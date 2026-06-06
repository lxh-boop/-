from __future__ import annotations

import json

from app.services.model_search_results import (
    load_daily_returns_for_strategy,
    load_table_file,
    make_strategy_from_row,
    save_selected_strategy,
)


def test_model_search_table_loads(fixtures_dir):
    df = load_table_file(fixtures_dir / "sample_search_results.csv")
    assert len(df) == 2
    assert "target_hit" in df.columns


def test_model_search_missing_file_returns_empty(tmp_path):
    df = load_table_file(tmp_path / "missing.csv")
    assert df.empty


def test_failed_rows_can_be_loaded(sample_search_results_df):
    failed = sample_search_results_df[sample_search_results_df["status"] == "failed"]
    assert len(failed) == 1


def test_target_hit_filter(sample_search_results_df):
    hits = sample_search_results_df[sample_search_results_df["target_hit"].astype(str).str.lower() == "true"]
    assert hits["run_id"].tolist() == ["run1"]


def test_missing_daily_returns_path_gives_empty_frame(sample_search_results_df):
    row = sample_search_results_df[sample_search_results_df["status"] == "failed"].iloc[0]
    assert load_daily_returns_for_strategy(row).empty


def test_save_selected_strategy_writes_json(tmp_path, monkeypatch, sample_search_results_df):
    import app.services.model_search_results as service

    monkeypatch.setattr(service, "SELECTED_STRATEGY_PATH", tmp_path / "selected_strategy.json")
    strategy = make_strategy_from_row(sample_search_results_df.iloc[0])
    save_selected_strategy(strategy)
    data = json.loads((tmp_path / "selected_strategy.json").read_text(encoding="utf-8"))
    assert data["run_id"] == "run1"
    assert data["topk"] == 1
