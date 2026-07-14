from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from database.repositories import AgentRepository
from scoring.schemas import FusionInput, FusionOutput


def decision_id_for(output: FusionOutput) -> str:
    return f"fusion_{output.user_id}_{output.trade_date}_{output.stock_code}".replace("-", "")


def build_decision_log_record(
    output: FusionOutput,
    fusion_input: FusionInput | None = None,
    evidence_snapshot: list[dict[str, Any]] | None = None,
    retrieval_id: str = "",
    decision_id: str | None = None,
) -> dict[str, Any]:
    user_constraint = fusion_input.user_constraints.to_dict() if fusion_input and fusion_input.user_constraints else {}
    triggered = [rule.to_dict() for rule in output.triggered_rules]
    return {
        "decision_id": decision_id or decision_id_for(output),
        "user_id": output.user_id,
        "trade_date": output.trade_date,
        "stock_code": output.stock_code,
        "original_pred_score": output.original_pred_score,
        "original_pred_rank": output.original_pred_rank,
        "news_adjustment": json.dumps(
            {
                "news_adjustment": output.news_adjustment,
                "effective_news_adjustment": output.effective_news_adjustment,
                "ai_reliability_weight": output.ai_reliability_weight,
                "evidence_news_ids": output.evidence_news_ids,
            },
            ensure_ascii=False,
        ),
        "risk_adjustment": "",
        "user_constraint": user_constraint,
        "triggered_rules": triggered,
        "combined_adjustment": output.combined_adjustment,
        "position_adjustment_ratio": output.position_adjustment_ratio,
        "final_reason": output.reason,
        "evidence_news_ids": output.evidence_news_ids,
        "evidence_chunk_ids": output.evidence_chunk_ids,
        "evidence_snapshot": evidence_snapshot or [],
        "retrieval_id": retrieval_id,
    }


def log_fusion_output(
    output: FusionOutput,
    db_path: str | Path | None = None,
    fusion_input: FusionInput | None = None,
    evidence_snapshot: list[dict[str, Any]] | None = None,
    retrieval_id: str = "",
    decision_id: str | None = None,
) -> dict[str, Any]:
    repo = AgentRepository(db_path)
    record = build_decision_log_record(
        output,
        fusion_input=fusion_input,
        evidence_snapshot=evidence_snapshot,
        retrieval_id=retrieval_id,
        decision_id=decision_id,
    )
    return repo.insert_decision_log(record)
