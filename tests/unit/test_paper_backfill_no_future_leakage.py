import pandas as pd

from database.repositories import NewsRepository
from pipelines.historical_news_loader import load_historical_news
from pipelines.historical_prediction_loader import load_historical_predictions


def test_historical_prediction_loader_does_not_use_latest_ranking(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    pd.DataFrame([{"date": "2026-06-12", "code": "000001", "score": 0.9}]).to_csv(
        output_dir / "ranking_latest.csv",
        index=False,
    )

    result = load_historical_predictions("2026-04-01", user_id="u1", output_dir=output_dir, db_path=tmp_path / "db.sqlite")

    assert result.status == "missing_prediction"
    assert result.predictions == []


def test_historical_news_loader_filters_future_publish_time(tmp_path) -> None:
    repo = NewsRepository(tmp_path / "db.sqlite")
    repo.insert_news_event(
        {
            "news_id": "n1",
            "source": "test",
            "title": "future news",
            "content": "future",
            "publish_time": "2026-04-02 09:30:00",
            "trade_date": "2026-04-02",
        }
    )
    repo.insert_news_stock_mapping(
        {
            "mapping_id": "m1",
            "news_id": "n1",
            "stock_code": "000001",
            "mapping_confidence": 0.9,
            "impact_direction": "negative",
            "impact_strength": 0.8,
            "created_at": "2026-04-02 09:31:00",
        }
    )

    result = load_historical_news("2026-04-01", ["000001"], db_path=tmp_path / "db.sqlite")

    assert result.status == "missing_or_incomplete"
    assert result.evidence == []
