from __future__ import annotations

import json

from database.repositories import AgentRepository, NewsRepository
from pipelines.schemas import PipelineContext, PipelineStatus
from pipelines.signal_fusion_pipeline import run_signal_fusion_pipeline
from scoring.schemas import ModelPredictionSignal, NewsEvidenceSignal


def test_signal_fusion_pipeline_outputs_recommendations_and_logs(tmp_path) -> None:
    context = PipelineContext(user_id="u1", trade_date="2026-06-11", output_dir=tmp_path / "outputs", db_path=tmp_path / "agent_quant.db")
    predictions = [ModelPredictionSignal("2026-06-11", "000001", 0.9, pred_rank=1, confidence="high")]
    evidence = [
        NewsEvidenceSignal(
            news_id="news_001",
            stock_code="000001",
            impact_direction="negative",
            impact_strength=0.8,
            impact_confidence=0.9,
            mapping_confidence=0.9,
            publish_time="2026-06-11 10:00:00",
            trade_date="2026-06-11",
            evidence_chunk_ids=["chunk_001"],
        )
    ]

    result = run_signal_fusion_pipeline(context, predictions, evidence)

    assert result.status == PipelineStatus.SUCCESS
    assert result.output_paths["latest_csv"].endswith("final_recommendations_latest.csv")
    assert result.decision_log_count == 1
    assert AgentRepository(tmp_path / "agent_quant.db").list_decision_logs(user_id="u1")


def test_signal_fusion_pipeline_dry_run_skips_writes(tmp_path) -> None:
    context = PipelineContext(user_id="u1", trade_date="2026-06-11", output_dir=tmp_path / "outputs", db_path=tmp_path / "agent_quant.db", dry_run=True)
    predictions = [ModelPredictionSignal("2026-06-11", "000001", 0.9, confidence="high")]

    result = run_signal_fusion_pipeline(context, predictions, [])

    assert result.status == PipelineStatus.SUCCESS
    assert result.output_paths == {}
    assert result.decision_log_count == 0


def test_signal_fusion_pipeline_filters_future_database_news(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"
    context = PipelineContext(user_id="u1", trade_date="2026-06-11", output_dir=tmp_path / "outputs", db_path=db_path)
    predictions = [ModelPredictionSignal("2026-06-11", "000001", 0.9, pred_rank=1, confidence="high")]

    repo = NewsRepository(db_path)
    repo.insert_news_event(
        {
            "news_id": "news_future",
            "source": "test",
            "title": "future risk",
            "content": "future risk",
            "publish_time": "2026-06-12 09:30:00",
            "trade_date": "2026-06-12",
            "importance_score": 1.0,
        }
    )
    repo.insert_news_stock_mapping(
        {
            "mapping_id": "mapping_future",
            "news_id": "news_future",
            "stock_code": "000001",
            "mapping_confidence": 1.0,
            "impact_confidence": 1.0,
            "impact_direction": "negative",
            "impact_strength": 1.0,
        }
    )

    result = run_signal_fusion_pipeline(context, predictions, [])

    assert result.status == PipelineStatus.SUCCESS
    output = result.recommendations[0].output
    assert output.news_adjustment == 0
    assert output.evidence_news_ids == []
