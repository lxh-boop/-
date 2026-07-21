from __future__ import annotations

import hashlib
from pathlib import Path

from strategy_apply_test_utils import apply_plan, apply_service


def test_apply_code_adds_new_plugin_without_overwriting_baseline(tmp_path) -> None:
    baseline = (
        tmp_path
        / "formal_project"
        / "portfolio"
        / "hierarchical_top10_allocator.py"
    )
    _, _, plan = apply_plan(tmp_path, implementation_type="code")
    before = hashlib.sha256(baseline.read_bytes()).hexdigest()

    result = apply_service(tmp_path).commit(
        user_id="u1",
        plan_id=plan.data["plan_id"],
        confirmation_token=plan.data["confirmation_token"],
        conversation_id="conv_1",
    )

    assert result.success
    assert Path(plan.data["formal_target"]).exists()
    assert hashlib.sha256(baseline.read_bytes()).hexdigest() == before
    assert "strategies" in Path(plan.data["formal_target"]).parts
    assert "generated" in Path(plan.data["formal_target"]).parts
