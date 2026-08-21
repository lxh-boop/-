from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from pipelines.daily_update_pipeline import run_daily_update_pipeline
from pipelines.schemas import PipelineContext
from scoring.schemas import COMPLIANCE_DISCLAIMER


def run_daily_pipeline(
    user_id: str = "default",
    trade_date: str = "latest",
    top_k: int = 50,
    dry_run: bool = True,
    paper_trading: bool = False,
    steps: list[str] | str | None = None,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    stock_pool: str = "csi300",
    model_name: str = "chronos_bolt_small",
    model_version: str = "latest",
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    context = PipelineContext(
        user_id=user_id,
        trade_date=trade_date,
        stock_pool=stock_pool,
        model_name=model_name,
        model_version=model_version,
        top_k=int(top_k),
        output_dir=output_dir,
        db_path=db_path,
        dry_run=bool(dry_run),
        paper_trading_enabled=bool(paper_trading),
    )
    run_fn = runner or run_daily_update_pipeline
    try:
        result = run_fn(context, steps=steps)
        payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        status = str(payload.get("status") or "")
        return {
            "ok": status in {"success", "partial"},
            "status": status,
            "message": payload.get("message", ""),
            "context": context.to_dict(),
            "result": payload,
            "errors": payload.get("errors", []),
            "warnings": payload.get("warnings", []),
            "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
            "note": "This tool can enable simulated paper trading only; it never sends broker orders.",
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "failed",
            "message": f"daily pipeline failed: {type(exc).__name__}: {exc}",
            "context": context.to_dict(),
            "result": {},
            "errors": [str(exc)],
            "warnings": [],
            "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
        }


def get_latest_outputs(
    output_dir: str | Path = "outputs",
    *,
    user_id: str = "default",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    del output_dir
    from database.repositories import (
        PortfolioRepository,
        PredictionRepository,
        RecommendationRepository,
    )

    portfolio = PortfolioRepository(db_path)
    counts = {
        "recommendations": len(RecommendationRepository(db_path).list_latest(user_id)),
        "paper_account": int(bool(portfolio.get_paper_account(f"paper_{user_id}"))),
        "paper_positions": len(portfolio.list_positions(user_id)),
        "paper_orders": len(portfolio.list_paper_orders(user_id=user_id)),
        "portfolio_risk_report": int(bool(portfolio.get_latest_risk_snapshot(user_id))),
        "latest_ranking": len(PredictionRepository(db_path).list_latest_predictions()),
    }
    return {
        "ok": any(counts.values()),
        "outputs": {
            name: {
                "path": f"database/{name}",
                "exists": count > 0,
                "size": count,
            }
            for name, count in counts.items()
        },
        "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
    }


def get_latest_pipeline_status(output_dir: str | Path = "outputs") -> dict[str, Any]:
    from agent.recommendation_tool import get_latest_recommendations
    from agent.report_tool import list_reports

    recommendations = get_latest_recommendations(output_dir=output_dir)
    reports = list_reports(output_dir=output_dir)
    latest_report = (reports.get("reports") or [{}])[0]
    return {
        "ok": bool(recommendations.get("ok") or reports.get("ok")),
        "recommendation_count": recommendations.get("total_count", 0),
        "adjustment_counts": recommendations.get("adjustment_counts", {}),
        "latest_report": latest_report,
        "message": "latest pipeline artifacts inspected",
        "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
    }
