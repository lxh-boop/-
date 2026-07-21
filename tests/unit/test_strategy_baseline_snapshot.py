from __future__ import annotations

from pipelines.paper_trading_pipeline import run_paper_trading_pipeline
from pipelines.schemas import PipelineContext
from strategies.registry import StrategyManifest, get_strategy_registry
from strategy_baseline_helpers import load_strategy_golden


def test_default_strategy_parameters_are_snapshotted() -> None:
    fixture = load_strategy_golden()

    assert fixture["defaults"] == {
        "strategy_mode": "hierarchical_top10",
        "entry_top_k": 10,
        "hold_buffer_rank": 15,
        "max_positions": 10,
        "target_invested_weight": 0.8,
        "minimum_cash_ratio": 0.05,
        "min_rebalance_weight_delta": 0.01,
    }


def test_phase0_registry_is_not_consumed_by_paper_pipeline(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    registry = get_strategy_registry(output_dir=output_dir)
    registry.register(
        StrategyManifest(
            strategy_id="phase0_not_consumed",
            strategy_name="Phase0 not consumed",
            version="v1",
            source_type="test",
            module_path="tests.fake",
            class_name="Fake",
            status="enabled",
            enabled_for_paper_trading=True,
        )
    )
    recommendations = [
        {
            "stock_code": f"{rank:06d}",
            "stock_name": f"S{rank}",
            "rank": rank,
            "original_rank": rank,
            "original_score": 1.0 - rank / 100.0,
            "current_price": 10.0,
            "risk_level": "low",
        }
        for rank in range(1, 16)
    ]

    result = run_paper_trading_pipeline(
        PipelineContext(
            user_id="phase0_user",
            trade_date="2026-07-16",
            output_dir=output_dir,
            dry_run=True,
        ),
        recommendations,
    )

    assert result.ok
    assert result.plan.execution_diagnostics["strategy_mode"] == (
        "hierarchical_top10"
    )
    assert "phase0_not_consumed" not in str(
        result.plan.execution_diagnostics
    )
