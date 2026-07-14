from __future__ import annotations

from database.repositories import AgentRepository
from scoring.decision_logger import log_fusion_output
from scoring.schemas import FusionInput, ModelPredictionSignal, PortfolioConstraintSignal, UserConstraintSignal
from scoring.signal_fusion import fuse_signal


def test_decision_logger_writes_agent_decision_log(tmp_path) -> None:
    fusion_input = FusionInput(
        model_prediction=ModelPredictionSignal("2026-06-11", "000001", 0.9, pred_rank=1, confidence="low"),
        user_constraints=UserConstraintSignal(user_id="u1"),
        portfolio_constraints=PortfolioConstraintSignal(confidence="low"),
    )
    output = fuse_signal(fusion_input)

    log_fusion_output(
        output,
        db_path=tmp_path / "agent_quant.db",
        fusion_input=fusion_input,
        evidence_snapshot=[{"chunk_id": "chunk_001", "text": "evidence"}],
        retrieval_id="retrieval_001",
    )

    rows = AgentRepository(tmp_path / "agent_quant.db").list_decision_logs(user_id="u1")

    assert len(rows) == 1
    assert "final_action" not in rows[0]
    assert rows[0]["combined_adjustment"] == output.combined_adjustment
    assert rows[0]["position_adjustment_ratio"] == output.position_adjustment_ratio
    assert rows[0]["evidence_snapshot"][0]["chunk_id"] == "chunk_001"
    assert rows[0]["triggered_rules"] == []
