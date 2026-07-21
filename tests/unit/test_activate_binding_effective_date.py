from __future__ import annotations

from datetime import UTC, datetime, timedelta

from strategies.runtime_resolver import StrategyRuntimeResolver
from strategy_binding_test_utils import (
    confirm_binding,
    create_binding_plan,
    register_strategy,
)


def test_activate_binding_effective_date_preserves_default_until_date(
    tmp_path,
) -> None:
    manifest = register_strategy(tmp_path)
    future = (datetime.now(UTC).date() + timedelta(days=7)).isoformat()
    result = confirm_binding(
        tmp_path,
        create_binding_plan(
            tmp_path,
            manifest,
            effective_from=future,
        ),
    )
    resolver = StrategyRuntimeResolver(
        db_path=tmp_path / "agent_quant.db",
        output_dir=tmp_path / "outputs",
    )
    before = resolver.resolve(
        user_id="u1",
        account_id="paper_u1",
    )
    after = resolver.resolve(
        user_id="u1",
        account_id="paper_u1",
        as_of_date=future,
    )

    assert result.data["binding"]["status"] == "scheduled"
    assert before.source == "builtin_default"
    assert after.strategy_id == manifest["strategy_id"]
    assert after.source == "account_binding"
