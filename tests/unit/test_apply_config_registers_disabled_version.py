from __future__ import annotations

from pathlib import Path

from agent.write_gateway import execute_confirmed_plan_v2
from strategies.registry import get_strategy_registry
from strategy_apply_test_utils import apply_plan
from strategy_workflow_test_utils import database_path


def test_apply_config_registers_disabled_version_via_write_gateway(
    tmp_path,
) -> None:
    _, _, plan = apply_plan(tmp_path)
    result = execute_confirmed_plan_v2(
        plan.data["plan_id"],
        plan.data["confirmation_token"],
        "u1",
        conversation_id="conv_1",
        run_id="run_gateway",
        db_path=database_path(tmp_path),
        output_dir=tmp_path / "outputs",
    )
    manifest = get_strategy_registry(
        output_dir=tmp_path / "outputs",
        db_path=database_path(tmp_path),
    ).get(
        plan.data["strategy_id"],
        plan.data["strategy_version"],
    )

    assert result.success
    assert Path(plan.data["formal_target"]).exists()
    assert manifest is not None
    assert manifest.status == "registered_disabled"
    assert manifest.enabled_for_paper_trading is False
    assert result.data["binding_changed"] is False
    assert result.data["positions_changed"] is False
