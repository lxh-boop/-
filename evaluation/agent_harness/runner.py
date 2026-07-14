from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd

from agent.executor import run_agent_request
from agent.runtime import load_run_snapshot
from agent.session.pending_action_store import load_pending_actions
from database.repositories import AgentRepository
from evaluation.agent_harness.assertions import assert_case_result
from evaluation.agent_harness.exporter import export_report
from evaluation.agent_harness.metrics import compute_metrics
from evaluation.agent_harness.schemas import HarnessCase, HarnessCaseResult
from news_db_sync import sync_event_cache_to_agent_db
from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.storage import PortfolioStorage


def _write_basic_fixture(
    *,
    output_dir: Path,
    db_path: Path,
    user_id: str,
    setup: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stock_code = str(setup.get("stock_code") or "000001").zfill(6)
    stock_name = str(setup.get("stock_name") or "Ping An Bank")
    price = float(setup.get("price") or 12.0)
    cash = float(setup.get("cash") or 100000.0)
    ranking_records = setup.get("ranking_records") or [
        {"rank": 1, "date": "2026-06-12", "code": stock_code, "name": stock_name, "close": price, "score": 0.90, "confidence": "high"},
        {"rank": 2, "date": "2026-06-12", "code": "600519", "name": "Kweichow Moutai", "close": 10.0, "score": 0.80, "confidence": "medium"},
    ]
    pd.DataFrame(ranking_records).to_csv(output_dir / "ranking_latest.csv", index=False, encoding="utf-8-sig")

    rec_dir = output_dir / "users" / user_id / "recommendations"
    rec_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "trade_date": "2026-06-12",
                "current_price": price,
                "original_score": 0.8,
                "final_score": 0.8,
                "news_adjustment": 0.0,
                "effective_news_adjustment": 0.0,
                "user_adjustment": 0.0,
                "combined_adjustment": 0.0,
                "target_weight": 0.05,
                "position_adjustment_ratio": 0.8,
                "ai_reliability_weight": 0.0,
                "risk_warning": "",
                "triggered_rules": "[]",
                "evidence_news_ids": "[]",
                "evidence_chunk_ids": "[]",
                "reason": "agent harness fixture",
            }
        ]
    ).to_csv(rec_dir / "final_recommendations_latest.csv", index=False, encoding="utf-8-sig")

    storage = PortfolioStorage(db_path, output_dir=output_dir / "portfolio" / user_id)
    account = create_default_account(user_id, initial_cash=cash)
    storage.save_account(account)
    positions = []
    if bool(setup.get("with_position", True)):
        positions.append(
            create_position(
                user_id=user_id,
                stock_code=stock_code,
                stock_name=stock_name,
                quantity=float(setup.get("quantity") or 1000),
                cost_price=price,
                current_price=price,
                total_assets=cash,
                industry=str(setup.get("industry") or "Bank"),
            )
        )
    storage.save_positions(positions)

    news_events = setup.get("news_events") or []
    if news_events:
        sync_event_cache_to_agent_db(
            stock_pool={stock_code: stock_name, "600519": "Kweichow Moutai"},
            db_path=db_path,
            output_dir=output_dir,
            events=pd.DataFrame(news_events),
        )


def _latest_pending_plan(user_id: str, output_dir: Path) -> dict[str, Any] | None:
    pending = load_pending_actions(user_id, output_dir)
    active = [
        plan
        for plan in pending.values()
        if plan.get("execution_status") not in {"executed", "cancelled"}
    ]
    if not active:
        return None
    return sorted(active, key=lambda item: str(item.get("created_at") or ""), reverse=True)[0]


def _mutate_account_cash(user_id: str, output_dir: Path, db_path: Path, amount: float) -> dict[str, Any]:
    storage = PortfolioStorage(db_path, output_dir=output_dir / "portfolio" / user_id)
    account = storage.load_account(f"paper_{user_id}")
    if account is None:
        return {"action_type": "mutate_account_cash", "success": False, "error": "missing_account"}
    updated = replace(account, cash=float(account.cash) + float(amount), total_assets=float(account.total_assets) + float(amount))
    storage.save_account(updated)
    return {"action_type": "mutate_account_cash", "success": True, "amount": amount}


def _confirm_latest_plan(
    *,
    case: HarnessCase,
    output_dir: Path,
    db_path: Path,
    duplicate: bool = False,
    llm_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = _latest_pending_plan(case.user_id, output_dir)
    if not plan:
        return {"action_type": "confirm_latest_plan", "duplicate": duplicate, "success": False, "error": "missing_pending_plan"}
    query = f"confirm execute {plan.get('plan_id')} token: {plan.get('confirmation_token')}"
    result = run_agent_request(
        query,
        user_id=case.user_id,
        output_dir=output_dir,
        db_path=db_path,
        reply_language="zh",
        llm_api_key=str((llm_settings or {}).get("llm_api_key") or ""),
        llm_base_url=str((llm_settings or {}).get("llm_base_url") or ""),
        llm_model=str((llm_settings or {}).get("llm_model") or ""),
    )
    return {
        "action_type": "confirm_latest_plan",
        "duplicate": duplicate,
        "success": bool(result.get("success")),
        "run_id": result.get("run_id"),
        "intent": result.get("intent"),
        "errors": (result.get("result") or {}).get("errors") or [],
        "answer": result.get("answer", "")[:500],
    }


def _run_actions(
    *,
    case: HarnessCase,
    output_dir: Path,
    db_path: Path,
    llm_settings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for action in case.actions:
        action_type = str(action.get("type") or "")
        if action_type == "mutate_account_cash":
            results.append(
                _mutate_account_cash(
                    case.user_id,
                    output_dir,
                    db_path,
                    amount=float(action.get("amount") or 1.0),
                )
            )
        elif action_type == "confirm_latest_plan":
            results.append(
                _confirm_latest_plan(
                    case=case,
                    output_dir=output_dir,
                    db_path=db_path,
                    duplicate=bool(action.get("duplicate", False)),
                    llm_settings=llm_settings,
                )
            )
        elif action_type == "reload_pending_run":
            plan = _latest_pending_plan(case.user_id, output_dir)
            run_id = str((plan or {}).get("run_id") or "")
            snapshot = load_run_snapshot(db_path, run_id) if run_id else {}
            results.append(
                {
                    "action_type": "reload_pending_run",
                    "success": bool(snapshot),
                    "run_id": run_id,
                    "status": (snapshot.get("run") or {}).get("status", ""),
                }
            )
        else:
            results.append({"action_type": action_type, "success": False, "error": "unsupported_action"})
    return results


def run_case(
    case: HarnessCase,
    *,
    base_output_dir: str | Path = "outputs",
    llm_settings: dict[str, Any] | None = None,
) -> HarnessCaseResult:
    case_output_dir = Path(base_output_dir) / "agent_harness" / case.case_id
    db_path = case_output_dir / "agent_harness.db"
    setup = dict(case.setup or {})
    _write_basic_fixture(output_dir=case_output_dir, db_path=db_path, user_id=case.user_id, setup=setup)

    started = time.perf_counter()
    result = run_agent_request(
        case.query,
        user_id=case.user_id,
        output_dir=case_output_dir,
        db_path=db_path,
        reply_language="zh",
        llm_api_key=str((llm_settings or {}).get("llm_api_key") or ""),
        llm_base_url=str((llm_settings or {}).get("llm_base_url") or ""),
        llm_model=str((llm_settings or {}).get("llm_model") or ""),
    )
    action_results = _run_actions(case=case, output_dir=case_output_dir, db_path=db_path, llm_settings=llm_settings)
    elapsed = time.perf_counter() - started
    run_id = str(result.get("run_id") or "")
    snapshot = load_run_snapshot(db_path, run_id) if run_id else {}
    assertions = assert_case_result(
        case,
        result=result,
        snapshot=snapshot,
        action_results=action_results,
        db_path=str(db_path),
    )
    passed = all(item.passed for item in assertions)
    final_status = str((snapshot.get("run") or {}).get("status") or (result.get("runtime") or {}).get("status") or "")
    return HarnessCaseResult(
        case=case,
        passed=passed,
        latency_seconds=round(elapsed, 4),
        run_id=run_id,
        final_status=final_status,
        result={
            "success": bool(result.get("success")),
            "intent": result.get("intent"),
            "runtime": result.get("runtime"),
            "orchestration": result.get("orchestration"),
            "tool_calls": result.get("tool_calls"),
            "answer_preview": str(result.get("answer") or "")[:800],
            "result": result.get("result"),
        },
        runtime_snapshot=snapshot,
        action_results=action_results,
        assertions=assertions,
        output_dir=str(case_output_dir),
        db_path=str(db_path),
    )


def run_harness(
    cases: list[HarnessCase],
    *,
    output_dir: str | Path = "outputs",
    llm_settings: dict[str, Any] | None = None,
    export: bool = True,
) -> dict[str, Any]:
    results = [run_case(case, base_output_dir=output_dir, llm_settings=llm_settings) for case in cases]
    metrics = compute_metrics(results)
    config = {
        "case_count": len(cases),
        "output_dir": str(output_dir),
        "uses_formal_entrypoint": "agent.executor.run_agent_request",
        "llm_configured": bool((llm_settings or {}).get("llm_api_key")),
    }
    report_path = export_report(output_dir=output_dir, config=config, metrics=metrics, results=results) if export else None
    return {
        "config": config,
        "metrics": metrics,
        "results": [result.to_dict() for result in results],
        "report_path": str(report_path) if report_path else "",
    }
