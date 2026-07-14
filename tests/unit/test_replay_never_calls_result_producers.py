from pipelines import paper_backfill_pipeline
from stage5q_helpers import write_stage5q_inputs


def test_replay_never_calls_result_producers(monkeypatch, tmp_path) -> None:
    write_stage5q_inputs(tmp_path, trade_date="2026-04-01", count=30)

    def forbidden(*args, **kwargs):
        raise AssertionError("result producer must not be called in stored-only replay")

    monkeypatch.setattr(paper_backfill_pipeline, "build_final_recommendations", forbidden)
    monkeypatch.setattr(paper_backfill_pipeline, "load_historical_news", forbidden)

    result = paper_backfill_pipeline.run_paper_trading_backfill(
        user_id="u1",
        start_date="2026-04-01",
        end_date="2026-04-01",
        output_dir=tmp_path,
        db_path=tmp_path / "agent.db",
        use_stored_ranking_only=True,
        use_stored_ai_adjustment_only=True,
        disable_model_inference=True,
        disable_news_fetch=True,
        disable_rag=True,
        disable_llm=True,
        disable_signal_fusion=True,
        audit_log="required",
        continue_on_error=True,
    )

    assert result.completed_days == 1
