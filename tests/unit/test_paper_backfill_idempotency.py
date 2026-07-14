import pandas as pd

from pipelines.paper_backfill_pipeline import run_paper_trading_backfill


def test_backfill_does_not_duplicate_existing_orders(tmp_path, monkeypatch) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    pd.DataFrame([{"date": "2026-04-01", "code": "000001", "score": 0.9, "rank": 1, "close": 10}]).to_csv(
        output_dir / "ranking_20260401_chronos_bolt_small.csv",
        index=False,
    )
    order_dir = output_dir / "portfolio" / "u1" / "history" / "orders"
    order_dir.mkdir(parents=True)
    pd.DataFrame([{"paper_action": "paper_buy", "quantity": 100, "trade_date": "2026-04-01"}]).to_csv(
        order_dir / "orders_20260401.csv",
        index=False,
    )
    calls = {"count": 0}

    def fake_paper(*args, **kwargs):
        calls["count"] += 1
        raise AssertionError("paper trading should be skipped when orders already exist")

    monkeypatch.setattr("pipelines.paper_backfill_pipeline.run_paper_trading_pipeline", fake_paper)

    result = run_paper_trading_backfill(
        user_id="u1",
        start_date="2026-04-01",
        end_date="2026-04-01",
        output_dir=output_dir,
        db_path=tmp_path / "db.sqlite",
        dry_run=True,
    )

    assert calls["count"] == 0
    assert result.completed_days == 1
