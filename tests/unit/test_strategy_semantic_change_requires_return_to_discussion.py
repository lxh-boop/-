from __future__ import annotations

import hashlib
from pathlib import Path

from strategy_workflow_test_utils import (
    prepare_proposal,
    proposal_service,
)


def test_strategy_semantic_change_requires_return_to_discussion(tmp_path) -> None:
    formal = Path("portfolio/hierarchical_top10_allocator.py")
    before = hashlib.sha256(formal.read_bytes()).hexdigest()
    draft, result = prepare_proposal(
        tmp_path,
        {
            "implementation_type": "config",
            "config": {
                "target_invested_weight": 0.95,
                "minimum_cash_ratio": 0.10,
            },
        },
    )
    proposal_id = draft.data["proposal"]["proposal_id"]
    proposal = proposal_service(tmp_path).get(proposal_id, user_id="u1")

    assert result.success is False
    assert "strategy_validation_failed" in result.errors
    assert result.data["status"] == "validation_failed"
    assert proposal.status == "revising"
    assert hashlib.sha256(formal.read_bytes()).hexdigest() == before
