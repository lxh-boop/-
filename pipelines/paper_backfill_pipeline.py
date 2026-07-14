from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from config import DEFAULT_INITIAL_CASH, DEFAULT_PAPER_TRADING_START_DATE
from evaluation.reliability_updater import DEFAULT_AI_RELIABILITY_WEIGHT
from pipelines.backfill_state import BackfillState, backup_backfill_outputs, load_backfill_state, save_backfill_state
from pipelines.daily_result_source_audit import FAILED_CONTINUE, PRICE_INCOMPLETE_CONTINUE, READY, audit_daily_result_sources, load_daily_source_audit_rows
from pipelines.historical_account_audit import backup_account_history
from pipelines.historical_account_replayer import replay_hold_day
from pipelines.historical_ai_adjustment_loader import load_historical_ai_adjustments
from pipelines.historical_news_loader import load_historical_news
from pipelines.historical_prediction_loader import load_historical_predictions
from pipelines.paper_trading_pipeline import run_paper_trading_pipeline
from pipelines.replay_audit_ledger import ReplayAuditLedger, create_replay_run_id
from pipelines.schemas import PipelineContext, PipelineStatus
from portfolio.storage import PortfolioStorage
from portfolio.paper_account import create_default_account
from portfolio.cash_flow import reset_cash_flows_from_date
from scheduler.trading_calendar import get_latest_trading_day, get_next_trading_day, is_trading_day, parse_date
from scheduler.user_job_runner import has_existing_orders_for_trade_date
from scoring.final_score import build_final_recommendations, save_final_recommendations
from scoring.schemas import UserConstraintSignal


@dataclass(frozen=True)
class PaperBackfillResult:
    user_id: str
    start_date: str
    actual_start_date: str
    end_date: str
    status: str
    completed_days: int = 0
    skipped_days: int = 0
    failed_days: int = 0
    missing_prediction_days: list[str] = field(default_factory=list)
    missing_ai_adjustment_days: list[str] = field(default_factory=list)
    result_mismatch_days: list[str] = field(default_factory=list)
    missing_news_days: list[str] = field(default_factory=list)
    nonzero_order_count: int = 0
    zero_order_count: int = 0
    buy_order_count: int = 0
    sell_order_count: int = 0
    nav_record_count: int = 0
    cumulative_fee: float = 0.0
    current_position_count: int = 0
    cumulative_deposit: float = 0.0
    cumulative_withdrawal: float = 0.0
    net_contribution: float = 0.0
    current_total_assets: float = 0.0
    absolute_profit: float = 0.0
    time_weighted_return: float = 0.0
    max_drawdown: float = 0.0
    diagnostic_day_count: int = 0
    average_total_asset: float = 0.0
    average_reserved_cash: float = 0.0
    average_planned_investable_cash: float = 0.0
    average_initial_allocated_cash: float = 0.0
    average_released_budget: float = 0.0
    average_redistributed_cash: float = 0.0
    average_actual_invested_cash: float = 0.0
    average_unavoidable_residual_cash: float = 0.0
    average_capital_utilization_rate: float = 0.0
    average_recursive_round_count: float = 0.0
    max_recursive_round_count: int = 0
    lot_removed_stock_count: int = 0
    average_actual_position_count: float = 0.0
    main_portfolio_max_actual_weight: float = 0.0
    max_single_actual_weight: float = 0.0
    state_path: str = ""
    stored_only_mode: bool = False
    run_id: str = ""
    audit_log_dir: str = ""
    source_audit_path: str = ""
    source_audit_summary_path: str = ""
    failed_continue_day_count: int = 0
    price_incomplete_continue_day_count: int = 0
    successful_strategy_day_count: int = 0
    daily_audit_json_count: int = 0
    daily_audit_markdown_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_backfill_start_date(start_date: str = DEFAULT_PAPER_TRADING_START_DATE) -> str:
    value = parse_date(start_date)
    if is_trading_day(value):
        return value.strftime("%Y-%m-%d")
    return get_next_trading_day(value - timedelta(days=1)).strftime("%Y-%m-%d")


def resolve_backfill_end_date(end_date: str = "latest") -> str:
    if str(end_date or "").lower() == "latest":
        return get_latest_trading_day(datetime.now()).strftime("%Y-%m-%d")
    return parse_date(end_date).strftime("%Y-%m-%d")


def trading_days_between(start_date: str, end_date: str) -> list[str]:
    start = parse_date(start_date)
    end = parse_date(end_date)
    if end < start:
        raise ValueError("end_date cannot be earlier than start_date")
    days: list[str] = []
    current = start
    while current <= end:
        if is_trading_day(current):
            days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return days


def load_paper_backfill_status(user_id: str, output_dir: str | Path = "outputs") -> dict[str, Any]:
    state = load_backfill_state(user_id, output_dir)
    return state.to_dict() if state else {}


def _stock_codes(predictions) -> list[str]:
    return [item.stock_code for item in predictions if item.stock_code]


def _nonzero_order_count(orders) -> int:
    return sum(1 for order in orders if float(getattr(order, "quantity", 0.0) or 0.0) > 0)


def _average_diagnostic(rows: list[dict[str, Any]], key: str) -> float:
    values = []
    for row in rows:
        try:
            values.append(float(row.get(key) or 0.0))
        except Exception:
            continue
    if not values:
        return 0.0
    return sum(values) / len(values)


def _diagnostic_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    round_counts = []
    removed_counts = []
    position_counts = []
    actual_ratios = []
    max_weights = []
    for row in rows:
        lot_rounds = row.get("lot_execution_rounds") or []
        removed = row.get("removed_candidates") or []
        try:
            round_counts.append(len(lot_rounds))
        except Exception:
            round_counts.append(0)
        try:
            removed_counts.append(len(removed))
        except Exception:
            removed_counts.append(0)
        try:
            position_counts.append(float(row.get("executable_candidate_count") or 0.0))
            actual_ratios.append(float(row.get("actual_top10_ratio") or 0.0))
            max_weights.append(float(row.get("maximum_position_weight") or 0.0))
        except Exception:
            continue
    return {
        "diagnostic_day_count": len(rows),
        "average_total_asset": _average_diagnostic(rows, "total_asset"),
        "average_reserved_cash": _average_diagnostic(rows, "reserved_cash"),
        "average_planned_investable_cash": _average_diagnostic(rows, "planned_investable_cash"),
        "average_initial_allocated_cash": _average_diagnostic(rows, "initial_allocated_cash"),
        "average_released_budget": _average_diagnostic(rows, "released_budget"),
        "average_redistributed_cash": _average_diagnostic(rows, "redistributed_cash"),
        "average_actual_invested_cash": _average_diagnostic(rows, "actual_invested_cash"),
        "average_unavoidable_residual_cash": _average_diagnostic(rows, "unavoidable_residual_cash"),
        "average_capital_utilization_rate": _average_diagnostic(rows, "capital_utilization_rate"),
        "average_recursive_round_count": (sum(round_counts) / len(round_counts)) if round_counts else 0.0,
        "max_recursive_round_count": max(round_counts or [0]),
        "lot_removed_stock_count": int(sum(removed_counts)),
        "average_actual_position_count": (sum(position_counts) / len(position_counts)) if position_counts else 0.0,
        "main_portfolio_max_actual_weight": max(actual_ratios or [0.0]),
        "max_single_actual_weight": max(max_weights or [0.0]),
    }


def _load_account_summary(user_id: str, output_dir: str | Path, db_path: str | Path | None) -> dict[str, Any]:
    storage = PortfolioStorage(db_path, output_dir=Path(output_dir) / "portfolio" / str(user_id))
    account = storage.load_account(f"paper_{user_id}")
    positions = storage.load_positions(user_id)
    if not account:
        return {}
    nav_history = storage.load_nav_history(user_id)
    return {
        "current_position_count": len([item for item in positions if float(item.quantity or 0.0) > 0]),
        "cumulative_deposit": account.cumulative_deposit,
        "cumulative_withdrawal": account.cumulative_withdrawal,
        "net_contribution": account.net_contribution,
        "current_total_assets": account.total_assets,
        "absolute_profit": account.absolute_profit,
        "time_weighted_return": account.time_weighted_return,
        "max_drawdown": account.max_drawdown,
        "cumulative_fee": account.cumulative_fee,
        "nav_record_count": len(nav_history),
    }


def _token(value: str) -> str:
    return str(value or "").replace("-", "")[:8]


def _restore_or_initialize_baseline(
    user_id: str,
    actual_start: str,
    initial_cash: float,
    output_dir: str | Path,
    db_path: str | Path | None,
    dry_run: bool,
    prefer_previous_snapshot: bool,
) -> None:
    if dry_run:
        return
    root = Path(output_dir) / "portfolio" / str(user_id)
    storage = PortfolioStorage(db_path, output_dir=root)
    start_token = _token(actual_start)
    account_source: Path | None = None
    position_source: Path | None = None
    if prefer_previous_snapshot:
        account_dir = root / "history" / "accounts"
        candidates = []
        if account_dir.exists():
            for path in account_dir.glob("account_*.json"):
                token = path.stem.replace("account_", "")[:8]
                if len(token) == 8 and token.isdigit() and token < start_token:
                    candidates.append((token, path))
        if candidates:
            _, account_source = sorted(candidates)[-1]
            pos_path = root / "history" / "positions" / f"positions_{account_source.stem.replace('account_', '')[:8]}.csv"
            if pos_path.exists():
                position_source = pos_path
    if account_source:
        payload = account_source.read_text(encoding="utf-8")
        root.mkdir(parents=True, exist_ok=True)
        storage.account_path.write_text(payload, encoding="utf-8")
        storage.account_latest_path.write_text(payload, encoding="utf-8")
        if position_source:
            text = position_source.read_text(encoding="utf-8-sig")
            storage.positions_path.parent.mkdir(parents=True, exist_ok=True)
            storage.positions_path.write_text(text, encoding="utf-8-sig")
            storage.positions_latest_path.write_text(text, encoding="utf-8-sig")
        return
    account = create_default_account(user_id, initial_cash=initial_cash)
    storage.save_account(account)
    storage.save_positions([])


def run_paper_trading_backfill(
    user_id: str,
    start_date: str = DEFAULT_PAPER_TRADING_START_DATE,
    end_date: str = "latest",
    initial_cash: float | None = None,
    resume: bool = True,
    force: bool = False,
    dry_run: bool = False,
    skip_news: bool = False,
    skip_evaluation: bool = False,
    top_k: int = 15,
    strategy: str = "hierarchical_top10",
    entry_top_k: int = 10,
    hold_buffer_rank: int = 15,
    max_positions: int = 10,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    use_stored_ranking_only: bool = False,
    use_stored_ai_adjustment_only: bool = False,
    disable_model_inference: bool = False,
    disable_news_fetch: bool = False,
    disable_rag: bool = False,
    disable_llm: bool = False,
    disable_signal_fusion: bool = False,
    use_full_stored_ai_results: bool = False,
    recursive_lot_reallocation: bool = False,
    audit_log: str = "optional",
    continue_on_error: bool = False,
    audit_root: str | Path = "runtime/replay_audit",
) -> PaperBackfillResult:
    actual_start = resolve_backfill_start_date(start_date)
    resolved_end = resolve_backfill_end_date(end_date)
    days = trading_days_between(actual_start, resolved_end)
    initial_cash = float(initial_cash if initial_cash is not None else DEFAULT_INITIAL_CASH)
    prior_state = load_backfill_state(user_id, output_dir) if resume and not force else None
    previous_run_id = ""
    if force:
        old_state = load_backfill_state(user_id, output_dir)
        previous_run_id = old_state.current_run_id if old_state else ""
    state = prior_state or BackfillState(
        user_id=user_id,
        start_date=start_date,
        end_date=resolved_end,
        current_run_id=create_replay_run_id("backfill"),
    )
    state.start_date = start_date
    state.end_date = resolved_end
    state.status = "running"
    if force:
        backup_backfill_outputs(user_id, actual_start, output_dir=output_dir, run_id=previous_run_id or state.current_run_id)
        stage5o_backup = backup_account_history(user_id, output_dir=output_dir)
        if stage5o_backup:
            state.errors = [item for item in state.errors if "stage5o backup" not in item]
        state.completed_days = []
        state.skipped_days = []
        state.failed_days = []
        state.errors = []
    if force or prior_state is None:
        reset_cash_flows_from_date(
            user_id,
            actual_start,
            db_path=db_path,
            output_dir=output_dir,
            use_database=not dry_run,
        )
        _restore_or_initialize_baseline(
            user_id,
            actual_start,
            initial_cash,
            output_dir,
            db_path,
            dry_run,
            prefer_previous_snapshot=force and actual_start != resolve_backfill_start_date(DEFAULT_PAPER_TRADING_START_DATE),
        )
    save_backfill_state(state, output_dir)

    missing_prediction: list[str] = []
    missing_ai_adjustment: list[str] = []
    result_mismatch: list[str] = []
    missing_news: list[str] = []
    warnings: list[str] = []
    diagnostic_rows: list[dict[str, Any]] = []
    nonzero_orders = 0
    zero_orders = 0
    buy_orders = 0
    sell_orders = 0
    stored_only_mode = bool(
        use_stored_ranking_only
        or use_stored_ai_adjustment_only
        or disable_model_inference
        or disable_news_fetch
        or disable_rag
        or disable_llm
        or disable_signal_fusion
        or use_full_stored_ai_results
        or recursive_lot_reallocation
    )
    fixed_top10_mode = str(strategy or "").lower() in {"fixed_original_top10_ai_weight", "hierarchical_top10"}
    effective_top_k = 0 if use_full_stored_ai_results else max(int(top_k or 0), int(entry_top_k or 10), int(hold_buffer_rank or 15), 30 if stored_only_mode else 0)
    audit_required = str(audit_log or "").lower() == "required"
    source_audit_result = None
    source_audit_rows: dict[str, dict[str, Any]] = {}
    ledger: ReplayAuditLedger | None = None
    if audit_required:
        source_audit_result = audit_daily_result_sources(
            user_id=user_id,
            start_date=actual_start,
            end_date=resolved_end,
            output_dir=output_dir,
            db_path=db_path,
            minimum_required_count=10 if (use_full_stored_ai_results or fixed_top10_mode) else 30,
            full_ai_results=use_full_stored_ai_results,
        )
        source_audit_rows = load_daily_source_audit_rows(source_audit_result.daily_report_path)
        ledger = ReplayAuditLedger(
            user_id=user_id,
            run_id=state.current_run_id,
            start_date=actual_start,
            end_date=resolved_end,
            audit_root=audit_root,
            output_dir=output_dir,
            strategy_name=strategy,
            database_path=db_path,
            source_audit_path=source_audit_result.daily_report_path,
            source_audit_summary_path=source_audit_result.summary_path,
        )
        ledger.start()

    for trade_date in days:
        if resume and not force and trade_date in set(state.completed_days):
            continue
        try:
            storage = PortfolioStorage(db_path, output_dir=Path(output_dir) / "portfolio" / str(user_id), use_database=not dry_run)
            opening_account = storage.load_account(f"paper_{user_id}")
            opening_positions = storage.load_positions(user_id)
            source_audit_row = source_audit_rows.get(trade_date, {})
            prediction = load_historical_predictions(
                trade_date,
                user_id=user_id,
                output_dir=output_dir,
                db_path=db_path,
                top_k=effective_top_k,
            )
            warnings.extend(prediction.warnings)
            source_status = str(source_audit_row.get("final_validation_status") or "")
            if prediction.status != "success":
                missing_prediction.append(trade_date)
                reason = ";".join(source_audit_row.get("validation_errors", "").splitlines()) or f"original ranking status={prediction.status}"
                failure_log = ""
                if ledger:
                    failure_log = str(
                        ledger.write_failure_log(
                            trade_date=trade_date,
                            step="load_original_ranking",
                            message=reason,
                            source=source_audit_row,
                            previous_success_trade_date=state.last_completed_trade_date,
                        )
                    )
                replay = replay_hold_day(
                    user_id,
                    trade_date,
                    initial_cash=initial_cash,
                    output_dir=output_dir,
                    db_path=db_path,
                    dry_run=dry_run,
                    replay_status=FAILED_CONTINUE,
                    failure_reason=reason,
                )
                warnings.extend(replay.warnings)
                if ledger:
                    ledger.write_daily(
                        trade_date=trade_date,
                        status=FAILED_CONTINUE,
                        source_audit_row=source_audit_row,
                        prediction=prediction,
                        ai_adjustment=None,
                        opening_account=opening_account,
                        opening_positions=opening_positions,
                        replay_result=replay,
                        failure_errors=[reason],
                        failure_log_path=failure_log,
                    )
                state.skipped_days.append(trade_date)
                state.completed_days.append(trade_date)
                state.last_completed_trade_date = trade_date
                save_backfill_state(state, output_dir)
                continue

            if stored_only_mode:
                ai_adjustment = load_historical_ai_adjustments(
                    trade_date,
                    prediction,
                    user_id=user_id,
                    output_dir=output_dir,
                    top_k=effective_top_k,
                    full_results=use_full_stored_ai_results,
                )
                warnings.extend(ai_adjustment.warnings)
                if ai_adjustment.status != "success":
                    if ai_adjustment.status == "result_mismatch":
                        result_mismatch.append(trade_date)
                        warnings.extend(f"{trade_date}: {reason}" for reason in ai_adjustment.mismatch_reasons[:10])
                    else:
                        missing_ai_adjustment.append(trade_date)
                    reason = "; ".join(ai_adjustment.mismatch_reasons[:10] or ai_adjustment.warnings or [f"ai adjustment status={ai_adjustment.status}"])
                    failure_log = ""
                    if ledger:
                        failure_log = str(
                            ledger.write_failure_log(
                                trade_date=trade_date,
                                step="load_stored_ai_adjustment",
                                message=reason,
                                source=source_audit_row,
                                previous_success_trade_date=state.last_completed_trade_date,
                            )
                        )
                    replay = replay_hold_day(
                        user_id,
                        trade_date,
                        initial_cash=initial_cash,
                        output_dir=output_dir,
                        db_path=db_path,
                        dry_run=dry_run,
                        replay_status=FAILED_CONTINUE,
                        failure_reason=reason,
                    )
                    warnings.extend(replay.warnings)
                    if ledger:
                        ledger.write_daily(
                            trade_date=trade_date,
                            status=FAILED_CONTINUE,
                            source_audit_row=source_audit_row,
                            prediction=prediction,
                            ai_adjustment=ai_adjustment,
                            opening_account=opening_account,
                            opening_positions=opening_positions,
                            replay_result=replay,
                            failure_errors=[reason],
                            failure_log_path=failure_log,
                        )
                    state.skipped_days.append(trade_date)
                    state.completed_days.append(trade_date)
                    state.last_completed_trade_date = trade_date
                    save_backfill_state(state, output_dir)
                    continue
                recommendations = ai_adjustment.records
                if audit_required and source_status == FAILED_CONTINUE:
                    reason = source_audit_row.get("validation_errors", "") or "daily source audit failed"
                    failure_log = ""
                    if ledger:
                        failure_log = str(
                            ledger.write_failure_log(
                                trade_date=trade_date,
                                step="daily_source_validation",
                                message=reason,
                                source=source_audit_row,
                                previous_success_trade_date=state.last_completed_trade_date,
                            )
                        )
                    replay = replay_hold_day(
                        user_id,
                        trade_date,
                        initial_cash=initial_cash,
                        output_dir=output_dir,
                        db_path=db_path,
                        dry_run=dry_run,
                        replay_status=FAILED_CONTINUE,
                        failure_reason=reason,
                    )
                    warnings.extend(replay.warnings)
                    if ledger:
                        ledger.write_daily(
                            trade_date=trade_date,
                            status=FAILED_CONTINUE,
                            source_audit_row=source_audit_row,
                            prediction=prediction,
                            ai_adjustment=ai_adjustment,
                            opening_account=opening_account,
                            opening_positions=opening_positions,
                            replay_result=replay,
                            failure_errors=[reason],
                            failure_log_path=failure_log,
                        )
                    state.skipped_days.append(trade_date)
                    state.completed_days.append(trade_date)
                    state.last_completed_trade_date = trade_date
                    save_backfill_state(state, output_dir)
                    continue
            elif skip_news:
                news_evidence = []
                missing_news.append(trade_date)
                recommendations = build_final_recommendations(
                    prediction.predictions,
                    news_stock_mapping=news_evidence,
                    user_profile=UserConstraintSignal(user_id=user_id),
                    ai_reliability_weight=DEFAULT_AI_RELIABILITY_WEIGHT,
                )
            else:
                news = load_historical_news(
                    trade_date,
                    _stock_codes(prediction.predictions),
                    db_path=db_path,
                    decision_time=f"{trade_date} 15:00:00",
                )
                news_evidence = news.evidence
                warnings.extend(news.warnings)
                if news.status != "success":
                    missing_news.append(trade_date)
                recommendations = build_final_recommendations(
                    prediction.predictions,
                    news_stock_mapping=news_evidence,
                    user_profile=UserConstraintSignal(user_id=user_id),
                    ai_reliability_weight=DEFAULT_AI_RELIABILITY_WEIGHT,
                )
            if not dry_run and not stored_only_mode:
                rec_dir = Path(output_dir) / "users" / str(user_id) / "recommendations"
                save_final_recommendations(recommendations, output_dir=rec_dir, trade_date=trade_date)

            if has_existing_orders_for_trade_date(user_id, trade_date, output_dir=output_dir) and not force:
                warnings.append(f"orders already exist for {user_id} {trade_date}; skipped duplicate paper execution.")
                replay = replay_hold_day(user_id, trade_date, initial_cash=initial_cash, output_dir=output_dir, db_path=db_path, dry_run=dry_run)
                if ledger:
                    ledger.write_daily(
                        trade_date=trade_date,
                        status="success",
                        source_audit_row=source_audit_row,
                        prediction=prediction,
                        ai_adjustment=ai_adjustment if stored_only_mode else None,
                        opening_account=opening_account,
                        opening_positions=opening_positions,
                        replay_result=replay,
                    )
            else:
                context = PipelineContext(
                    user_id=user_id,
                    trade_date=trade_date,
                    decision_time=f"{trade_date} 15:00:00",
                    top_k=effective_top_k,
                    output_dir=output_dir,
                    db_path=db_path,
                    dry_run=dry_run,
                    paper_trading_enabled=True,
                    strategy=strategy,
                    entry_top_k=entry_top_k,
                    hold_buffer_rank=hold_buffer_rank,
                    max_positions=max_positions,
                    run_id=state.current_run_id,
                    execution_source="backfill",
                )
                paper = run_paper_trading_pipeline(
                    context,
                    recommendations,
                    output_dir=Path(output_dir) / "portfolio" / str(user_id),
                )
                if paper.status != PipelineStatus.SUCCESS:
                    raise RuntimeError(paper.message)
                order_count = _nonzero_order_count(paper.orders)
                nonzero_orders += order_count
                if order_count == 0:
                    zero_orders += 1
                buy_orders += sum(1 for order in paper.orders if order.action == "buy")
                sell_orders += sum(1 for order in paper.orders if order.action == "sell")
                diagnostics = getattr(paper.plan, "execution_diagnostics", {}) if paper.plan else {}
                if isinstance(diagnostics, dict) and diagnostics:
                    diagnostic_rows.append(dict(diagnostics))
                if ledger:
                    ledger.write_daily(
                        trade_date=trade_date,
                        status=PRICE_INCOMPLETE_CONTINUE if source_status == PRICE_INCOMPLETE_CONTINUE else "success",
                        source_audit_row=source_audit_row,
                        prediction=prediction,
                        ai_adjustment=ai_adjustment if stored_only_mode else None,
                        opening_account=opening_account,
                        opening_positions=opening_positions,
                        paper_result=paper,
                    )

            state.completed_days.append(trade_date)
            state.last_completed_trade_date = trade_date
            save_backfill_state(state, output_dir)
        except Exception as exc:
            message = f"{trade_date}: {type(exc).__name__}: {exc}"
            source_audit_row = locals().get("source_audit_row", source_audit_rows.get(trade_date, {}))
            opening_account = locals().get("opening_account")
            opening_positions = locals().get("opening_positions", [])
            prediction = locals().get("prediction")
            ai_adjustment = locals().get("ai_adjustment")
            failure_log = ""
            replay = None
            if ledger:
                failure_log = str(
                    ledger.write_failure_log(
                        trade_date=trade_date,
                        step="paper_backfill_day",
                        exc=exc,
                        source=source_audit_row,
                        previous_success_trade_date=state.last_completed_trade_date,
                    )
                )
            try:
                replay = replay_hold_day(
                    user_id,
                    trade_date,
                    initial_cash=initial_cash,
                    output_dir=output_dir,
                    db_path=db_path,
                    dry_run=dry_run,
                    replay_status=FAILED_CONTINUE,
                    failure_reason=message,
                )
            except Exception as replay_exc:
                warnings.append(f"{trade_date}: failed to create conservative snapshot after error: {replay_exc}")
            if ledger:
                ledger.write_daily(
                    trade_date=trade_date,
                    status=FAILED_CONTINUE,
                    source_audit_row=source_audit_row,
                    prediction=prediction,
                    ai_adjustment=ai_adjustment,
                    opening_account=opening_account,
                    opening_positions=opening_positions,
                    replay_result=replay,
                    failure_errors=[message],
                    failure_log_path=failure_log,
                )
            state.failed_days.append(trade_date)
            state.completed_days.append(trade_date)
            state.last_completed_trade_date = trade_date
            state.errors.append(message)
            state.status = "partial_success" if continue_on_error or audit_required or resume else "failed"
            save_backfill_state(state, output_dir)
            if not (continue_on_error or audit_required or resume):
                raise
            warnings.append(message)

    state.status = "success" if not state.failed_days and not (audit_required and state.skipped_days) else "partial_success"
    state.completed_days = sorted(set(state.completed_days))
    state.skipped_days = sorted(set(state.skipped_days))
    state.failed_days = sorted(set(state.failed_days))
    state_path = save_backfill_state(state, output_dir)
    summary = _load_account_summary(user_id, output_dir, db_path)
    diagnostic_summary = _diagnostic_summary(diagnostic_rows)
    ledger_summary: dict[str, Any] = {}
    if ledger:
        ledger_status = "partial_success" if state.failed_days or state.skipped_days else "success"
        ledger_summary = ledger.finish(
            status=ledger_status,
            extra_summary={
                "backfill_state_path": str(state_path),
                "source_audit_path": source_audit_result.daily_report_path if source_audit_result else "",
                "source_audit_summary_path": source_audit_result.summary_path if source_audit_result else "",
            },
        )
    return PaperBackfillResult(
        user_id=user_id,
        start_date=start_date,
        actual_start_date=actual_start,
        end_date=resolved_end,
        status=state.status,
        completed_days=len(state.completed_days),
        skipped_days=len(state.skipped_days),
        failed_days=len(state.failed_days),
        missing_prediction_days=sorted(set(missing_prediction)),
        missing_ai_adjustment_days=sorted(set(missing_ai_adjustment)),
        result_mismatch_days=sorted(set(result_mismatch)),
        missing_news_days=sorted(set(missing_news)),
        nonzero_order_count=nonzero_orders,
        zero_order_count=zero_orders,
        buy_order_count=buy_orders,
        sell_order_count=sell_orders,
        state_path=str(state_path),
        stored_only_mode=stored_only_mode,
        run_id=state.current_run_id,
        audit_log_dir=str(ledger.root) if ledger else "",
        source_audit_path=source_audit_result.daily_report_path if source_audit_result else "",
        source_audit_summary_path=source_audit_result.summary_path if source_audit_result else "",
        failed_continue_day_count=int(ledger_summary.get("failed_continue_day_count", 0)),
        price_incomplete_continue_day_count=int(ledger_summary.get("price_incomplete_continue_day_count", 0)),
        successful_strategy_day_count=int(ledger_summary.get("success_day_count", 0)),
        daily_audit_json_count=int(ledger_summary.get("daily_json_count", 0)),
        daily_audit_markdown_count=int(ledger_summary.get("daily_markdown_count", 0)),
        warnings=warnings,
        errors=list(state.errors),
        **diagnostic_summary,
        **summary,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run AI paper trading historical backfill")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--start-date", default=DEFAULT_PAPER_TRADING_START_DATE)
    parser.add_argument("--end-date", default="latest")
    parser.add_argument("--initial-cash", type=float, default=None)
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-news", action="store_true")
    parser.add_argument("--skip-evaluation", action="store_true")
    parser.add_argument("--top-k", type=int, default=15)
    parser.add_argument("--strategy", default="hierarchical_top10")
    parser.add_argument("--entry-top-k", type=int, default=10)
    parser.add_argument("--hold-buffer-rank", type=int, default=15)
    parser.add_argument("--max-positions", type=int, default=10)
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--use-stored-ranking-only", action="store_true")
    parser.add_argument("--use-stored-ai-adjustment-only", action="store_true")
    parser.add_argument("--disable-model-inference", action="store_true")
    parser.add_argument("--disable-news-fetch", action="store_true")
    parser.add_argument("--disable-rag", action="store_true")
    parser.add_argument("--disable-llm", action="store_true")
    parser.add_argument("--disable-signal-fusion", action="store_true")
    parser.add_argument("--use-full-stored-ai-results", action="store_true")
    parser.add_argument("--recursive-lot-reallocation", action="store_true")
    parser.add_argument("--audit-log", choices=["optional", "required"], default="optional")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--audit-root", default="runtime/replay_audit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_paper_trading_backfill(
        user_id=args.user_id,
        start_date=args.start_date,
        end_date=args.end_date,
        initial_cash=args.initial_cash,
        resume=args.resume,
        force=args.force,
        dry_run=args.dry_run,
        skip_news=args.skip_news,
        skip_evaluation=args.skip_evaluation,
        top_k=args.top_k,
        strategy=args.strategy,
        entry_top_k=args.entry_top_k,
        hold_buffer_rank=args.hold_buffer_rank,
        max_positions=args.max_positions,
        output_dir=args.output_dir,
        db_path=args.db_path,
        use_stored_ranking_only=args.use_stored_ranking_only,
        use_stored_ai_adjustment_only=args.use_stored_ai_adjustment_only,
        disable_model_inference=args.disable_model_inference,
        disable_news_fetch=args.disable_news_fetch,
        disable_rag=args.disable_rag,
        disable_llm=args.disable_llm,
        disable_signal_fusion=args.disable_signal_fusion,
        use_full_stored_ai_results=args.use_full_stored_ai_results,
        recursive_lot_reallocation=args.recursive_lot_reallocation,
        audit_log=args.audit_log,
        continue_on_error=args.continue_on_error,
        audit_root=args.audit_root,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str))
    return 1 if result.status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
