from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

from config import AGENT_QUANT_DB_PATH
from database.repositories import UserRepository
from evaluation.evaluation_pipeline import evaluate_due_adjustments, update_ai_reliability
from portfolio.cash_flow import apply_cash_flows_to_account, list_cash_flows
from portfolio.paper_account import create_default_account
from portfolio.storage import PortfolioStorage
from pipelines.paper_trading_pipeline import run_paper_trading_pipeline
from pipelines.prediction_pipeline import run_prediction_pipeline
from pipelines.rag_pipeline import run_rag_pipeline
from pipelines.report_pipeline import run_report_pipeline
from pipelines.schemas import PipelineContext, PipelineStatus
from pipelines.signal_fusion_pipeline import run_signal_fusion_pipeline


def _stock_output_root(output_dir: str | Path = "outputs") -> Path:
    return Path(output_dir)


def user_recommendation_dir(user_id: str, output_dir: str | Path = "outputs") -> Path:
    return _stock_output_root(output_dir) / "users" / str(user_id) / "recommendations"


def user_report_dir(user_id: str, output_dir: str | Path = "outputs") -> Path:
    return _stock_output_root(output_dir) / "users" / str(user_id) / "reports"


def user_evaluation_dir(user_id: str, output_dir: str | Path = "outputs") -> Path:
    return _stock_output_root(output_dir) / "evaluation" / str(user_id)


def portfolio_user_dir(user_id: str, output_dir: str | Path = "outputs") -> Path:
    return _stock_output_root(output_dir) / "portfolio" / str(user_id)


def _safe_user_id(value: Any) -> str:
    return str(value or "").strip()


def get_active_user_ids(
    db_path: str | Path | None = AGENT_QUANT_DB_PATH,
    output_dir: str | Path = "outputs",
) -> list[str]:
    users: set[str] = set()
    try:
        for profile in UserRepository(db_path).list_user_profiles():
            user_id = _safe_user_id(profile.get("user_id"))
            if not user_id:
                continue
            is_active = profile.get("is_active", 1)
            if str(is_active).lower() not in {"0", "false", "no", "inactive"}:
                users.add(user_id)
    except Exception:
        pass

    root = Path(output_dir)
    for parent in [root / "users", root / "portfolio"]:
        if parent.exists():
            for child in parent.iterdir():
                if child.is_dir() and child.name not in {"history", "shared"}:
                    users.add(child.name)
    return sorted(users)


def _has_real_orders(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                action = str(row.get("paper_action") or row.get("action") or "")
                quantity = float(row.get("quantity") or row.get("order_quantity") or 0.0)
                if action in {"paper_buy", "paper_sell", "paper_reduce", "buy", "sell"} and quantity > 0:
                    return True
    except Exception:
        return False
    return False


def has_existing_orders_for_trade_date(user_id: str, trade_date: str, output_dir: str | Path = "outputs") -> bool:
    token = str(trade_date or "").replace("-", "")[:8]
    if len(token) != 8:
        return False
    path = portfolio_user_dir(user_id, output_dir) / "history" / "orders" / f"orders_{token}.csv"
    return _has_real_orders(path)


def apply_due_cash_flows_for_user(
    user_id: str,
    trade_date: str,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = AGENT_QUANT_DB_PATH,
    dry_run: bool = False,
) -> dict[str, Any]:
    storage = PortfolioStorage(db_path, output_dir=portfolio_user_dir(user_id, output_dir), use_database=not dry_run)
    account = storage.load_account(f"paper_{user_id}") or create_default_account(user_id)
    flows = list_cash_flows(user_id, db_path=db_path, output_dir=output_dir, use_database=not dry_run)
    updated, applied, warnings = apply_cash_flows_to_account(
        account,
        flows,
        trade_date,
        db_path=db_path,
        output_dir=output_dir,
        use_database=not dry_run,
        persist_status=not dry_run,
    )
    if applied and not dry_run:
        storage.save_account(updated)
        storage.write_daily_snapshot(account=updated, positions=storage.load_positions(user_id), orders=[], trade_date=trade_date)
    return {
        "applied_cash_flow_count": len(applied),
        "warnings": warnings,
        "cash": updated.cash,
        "total_assets": updated.total_assets,
    }


def _sync_legacy_recommendations(user_id: str, paths: dict[str, str], output_dir: str | Path = "outputs") -> None:
    root = Path(output_dir)
    legacy = root / "recommendations"
    legacy.mkdir(parents=True, exist_ok=True)
    for key, name in [("latest_csv", "final_recommendations_latest.csv"), ("latest_json", "final_recommendations_latest.json")]:
        source = paths.get(key)
        if source and Path(source).exists():
            shutil.copy2(source, legacy / name)
    dated = paths.get("dated_csv")
    if dated and Path(dated).exists():
        shutil.copy2(dated, legacy / Path(dated).name)


def run_user_daily_job(
    user_id: str,
    trade_date: str,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = AGENT_QUANT_DB_PATH,
    top_k: int = 50,
    dry_run: bool = False,
    skip_news: bool = False,
    skip_paper_trading: bool = False,
    force: bool = False,
    sync_legacy: bool = False,
    job_id: str = "",
    run_id: str = "",
    execution_source: str = "",
) -> dict[str, Any]:
    context = PipelineContext(
        user_id=user_id,
        trade_date=trade_date,
        decision_time="",
        top_k=top_k,
        output_dir=output_dir,
        db_path=db_path,
        dry_run=dry_run,
        paper_trading_enabled=not skip_paper_trading,
        job_id=job_id,
        run_id=run_id,
        execution_source=execution_source,
    )
    result: dict[str, Any] = {
        "user_id": user_id,
        "status": PipelineStatus.SUCCESS,
        "trade_date": trade_date,
        "warnings": [],
        "errors": [],
        "recommendation_count": 0,
        "paper_order_count": 0,
        "position_count": 0,
        "report_path": "",
        "output_paths": {},
    }

    prediction = run_prediction_pipeline(context)
    if prediction.status != PipelineStatus.SUCCESS:
        raise RuntimeError(prediction.message)

    if skip_news:
        rag = None
        evidence = []
        result["warnings"].append("news/RAG step skipped by scheduler option.")
    else:
        rag = run_rag_pipeline(context, prediction.predictions)
        evidence = rag.evidence
        result["warnings"].extend(rag.warnings)

    rec_dir = user_recommendation_dir(user_id, output_dir)
    scoring = run_signal_fusion_pipeline(context, prediction.predictions, evidence, output_dir=rec_dir)
    if scoring.status != PipelineStatus.SUCCESS:
        raise RuntimeError(scoring.message)
    result["recommendation_count"] = len(scoring.recommendations)
    result["output_paths"].update({f"recommendations.{k}": str(v) for k, v in scoring.output_paths.items()})
    if sync_legacy and not dry_run:
        _sync_legacy_recommendations(user_id, scoring.output_paths, output_dir)

    existing_orders = has_existing_orders_for_trade_date(user_id, trade_date, output_dir)
    paper = None
    if skip_paper_trading:
        result["warnings"].append("paper trading skipped by scheduler option.")
        cash_flow_result = apply_due_cash_flows_for_user(user_id, trade_date, output_dir, db_path, dry_run=dry_run)
        result["cash_flow"] = cash_flow_result
        result["warnings"].extend(cash_flow_result.get("warnings") or [])
    elif existing_orders and not force:
        result["warnings"].append(f"paper trading skipped because real orders already exist for {user_id} {trade_date}.")
        cash_flow_result = apply_due_cash_flows_for_user(user_id, trade_date, output_dir, db_path, dry_run=dry_run)
        result["cash_flow"] = cash_flow_result
        result["warnings"].extend(cash_flow_result.get("warnings") or [])
    elif existing_orders and force:
        result["warnings"].append(f"paper trading force run kept idempotent; existing real orders were not duplicated for {user_id} {trade_date}.")
        cash_flow_result = apply_due_cash_flows_for_user(user_id, trade_date, output_dir, db_path, dry_run=dry_run)
        result["cash_flow"] = cash_flow_result
        result["warnings"].extend(cash_flow_result.get("warnings") or [])
    else:
        paper = run_paper_trading_pipeline(context, scoring.recommendations, output_dir=portfolio_user_dir(user_id, output_dir))
        result["paper_order_count"] = len(paper.orders)
        result["position_count"] = len(paper.positions)
        result["output_paths"].update({f"paper.{k}": str(v) for k, v in paper.output_paths.items()})

    if not dry_run:
        eval_dir = user_evaluation_dir(user_id, output_dir)
        try:
            evaluation = evaluate_due_adjustments(as_of_date=trade_date, output_dir=eval_dir)
            reliability = update_ai_reliability(user_id=user_id, as_of_date=trade_date, output_dir=eval_dir)
            result["evaluation"] = {
                "evaluated_count": len(evaluation.get("evaluations", [])),
                "ai_reliability_weight": reliability.get("ai_reliability_weight"),
                "status": reliability.get("status"),
            }
        except Exception as exc:
            result["warnings"].append(f"evaluation update failed for {user_id}: {exc}")

    report = run_report_pipeline(
        context,
        prediction_result=prediction,
        rag_result=rag,
        scoring_result=scoring,
        paper_result=paper,
        output_dir=user_report_dir(user_id, output_dir),
    )
    result["report_path"] = report.report_path
    result["output_paths"]["report"] = report.report_path
    result["warnings"].extend(scoring.warnings)
    if paper:
        result["warnings"].extend(paper.warnings)
    return json.loads(json.dumps(result, ensure_ascii=False, default=str))
