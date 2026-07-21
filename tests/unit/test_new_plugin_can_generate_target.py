import sys

from pipelines.paper_trading_pipeline import run_paper_trading_pipeline
from pipelines.schemas import PipelineContext
from strategy_runtime_test_utils import bind_runtime, runtime_candidates


def test_new_plugin_can_generate_target(tmp_path) -> None:
    module_path = tmp_path / "phase6_plugin.py"
    module_path.write_text(
        """
from strategies.base import PortfolioStrategy, StrategyResult
class Phase6Plugin(PortfolioStrategy):
    strategy_id = "phase6_plugin"
    strategy_name = "Phase 6 plugin"
    version = "v1"
    def get_config_schema(self): return {"type": "object"}
    def validate_config(self, config): return []
    def generate_target(self, context, config):
        return StrategyResult(
            strategy_id=self.strategy_id,
            strategy_version=self.version,
            trade_date=context.trade_date,
            target_weights={"000001": 0.05},
            cash_weight=0.95,
        )
""",
        encoding="utf-8",
    )
    sys.path.insert(0, str(tmp_path))
    try:
        bind_runtime(
            tmp_path,
            config={"entry_top_k": 10, "max_positions": 10},
            module_path="phase6_plugin",
            class_name="Phase6Plugin",
            source_type="generated_plugin",
        )
        result = run_paper_trading_pipeline(
            PipelineContext(
                user_id="u1",
                trade_date="2026-07-16",
                output_dir=tmp_path / "outputs",
                db_path=tmp_path / "agent_quant.db",
                dry_run=True,
            ),
            runtime_candidates(),
        )
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("phase6_plugin", None)

    first = next(
        item for item in result.plan.decisions
        if item.stock_code == "000001"
    )
    assert result.plan.execution_diagnostics["strategy_mode"] == (
        "runtime_plugin"
    )
    assert first.target_weight == 0.05
