import json

from database.connection import get_connection
from pipelines.paper_trading_pipeline import run_paper_trading_pipeline
from pipelines.schemas import PipelineContext
from strategy_runtime_test_utils import bind_runtime, runtime_candidates


def test_rebalance_records_strategy_metadata(tmp_path) -> None:
    manifest, binding = bind_runtime(tmp_path)
    db_path = tmp_path / "agent_quant.db"
    result = run_paper_trading_pipeline(
        PipelineContext(
            user_id="u1",
            trade_date="2026-07-16",
            output_dir=tmp_path / "outputs",
            db_path=db_path,
        ),
        runtime_candidates(),
    )

    assert result.plan.binding_id == binding.binding_id
    assert result.orders
    assert all(item.strategy_id == manifest.strategy_id for item in result.orders)
    connection = get_connection(db_path)
    try:
        order = dict(
            connection.execute(
                "SELECT * FROM paper_order LIMIT 1"
            ).fetchone()
        )
        snapshot = dict(
            connection.execute(
                "SELECT * FROM paper_account_snapshot LIMIT 1"
            ).fetchone()
        )
    finally:
        connection.close()
    assert order["binding_id"] == binding.binding_id
    assert snapshot["strategy_id"] == manifest.strategy_id
    assert json.loads(snapshot["resolved_config_json"])[
        "entry_top_k"
    ] == 6
