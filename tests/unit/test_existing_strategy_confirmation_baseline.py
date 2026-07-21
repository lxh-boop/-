from __future__ import annotations

from agent.tools.strategy_builder_tool import prepare_strategy_change
from agent.write_gateway import execute_confirmed_plan_v2
from strategies.registry import get_strategy_registry


def test_existing_strategy_registration_requires_confirmation(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    db_path = tmp_path / "agent_quant.db"
    registry = get_strategy_registry(output_dir=output_dir, db_path=db_path)
    before = {
        (item.strategy_id, item.version)
        for item in registry.list(include_archived=True)
    }

    preview = prepare_strategy_change(
        "phase0_user",
        "长期使用前 8 名，现金保留 10%",
        output_dir=output_dir,
        db_path=db_path,
        session_id="phase0_session",
    )

    assert preview.success is True
    assert preview.requires_confirmation is True
    assert {
        (item.strategy_id, item.version)
        for item in registry.list(include_archived=True)
    } == before

    committed = execute_confirmed_plan_v2(
        preview.data["plan_id"],
        preview.data["confirmation_token"],
        "phase0_user",
        output_dir=output_dir,
        db_path=db_path,
    )

    assert committed.success is True
    manifest = committed.data["strategy_manifest"]
    assert manifest["enabled_for_paper_trading"] is False
    assert committed.data["enable_plan"]["plan_id"]
    registered = registry.get(
        manifest["strategy_id"],
        manifest["version"],
    )
    assert registered is not None
    assert registered.enabled_for_paper_trading is False
