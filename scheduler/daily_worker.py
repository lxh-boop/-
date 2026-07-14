from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from config import AGENT_QUANT_DB_PATH
from database.repositories import NewsRepository
from scheduler.job_lock import JobLock, JobLockError
from scheduler.job_state import run_recorded_step, save_job_status
from scheduler.schemas import JobStatus, SchedulerStatus, make_run_id, now_text
from scheduler.trading_calendar import get_latest_trading_day, is_trading_day, parse_date
from scheduler.user_job_runner import get_active_user_ids, run_user_daily_job


PUBLIC_MARKER_DIR = Path("runtime") / "jobs" / "public_tasks"
SCHEDULER_LOG_DIR = Path("logs") / "scheduler"


def _date_text(value: Any) -> str:
    return parse_date(value).strftime("%Y-%m-%d")


def _job_log_path(trade_date: str) -> Path:
    SCHEDULER_LOG_DIR.mkdir(parents=True, exist_ok=True)
    return SCHEDULER_LOG_DIR / f"daily_worker_{str(trade_date).replace('-', '')}.log"


def _append_log(trade_date: str, text: str) -> None:
    path = _job_log_path(trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(f"[{now_text()}] {text}\n")


def _public_marker_path(trade_date: str, root: str | Path = ".") -> Path:
    return Path(root) / PUBLIC_MARKER_DIR / f"public_{str(trade_date).replace('-', '')}.json"


def _public_already_done(trade_date: str, root: str | Path = ".") -> bool:
    path = _public_marker_path(trade_date, root)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("status") == SchedulerStatus.SUCCESS
    except Exception:
        return False


def _write_public_marker(trade_date: str, payload: dict[str, Any], root: str | Path = ".") -> None:
    path = _public_marker_path(trade_date, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _copy_ranking_to_shared(output_dir: str | Path, dry_run: bool) -> str:
    root = Path(output_dir)
    source = root / "ranking_latest.csv"
    shared = root / "shared" / "ranking_latest.csv"
    if not source.exists():
        raise FileNotFoundError(f"ranking_latest.csv not found: {source}")
    if not dry_run:
        shared.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, shared)
    return str(shared if not dry_run else source)


def _count_news(db_path: str | Path | None) -> tuple[int, int]:
    try:
        repo = NewsRepository(db_path)
        return len(repo.list_news_events()), len(repo.list_news_chunks())
    except Exception:
        return 0, 0


def run_public_daily_tasks(
    trade_date: str,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = AGENT_QUANT_DB_PATH,
    force: bool = False,
    dry_run: bool = False,
    skip_training: bool = False,
    skip_news: bool = False,
    root: str | Path = ".",
) -> dict[str, Any]:
    warnings: list[str] = []
    if _public_already_done(trade_date, root) and not force:
        return {
            "status": SchedulerStatus.SKIPPED,
            "warnings": [f"public tasks already completed for {trade_date}."],
            "metadata": {"public_task_once": True},
        }

    ranking_path = _copy_ranking_to_shared(output_dir, dry_run=dry_run)
    news_event_count = 0
    news_chunk_count = 0
    if skip_training:
        warnings.append("training/model refresh skipped by scheduler option.")
    if skip_news:
        warnings.append("news download/ingestion skipped by scheduler option.")
    else:
        news_event_count, news_chunk_count = _count_news(db_path)
        if news_event_count == 0:
            warnings.append("no news_event records found; scoring will keep news_adjustment_score neutral.")

    payload = {
        "status": SchedulerStatus.SUCCESS,
        "trade_date": trade_date,
        "ranking_output_path": ranking_path,
        "news_event_count": news_event_count,
        "news_chunk_count": news_chunk_count,
        "dry_run": dry_run,
        "finished_at": now_text(),
    }
    if not dry_run:
        _write_public_marker(trade_date, payload, root)
    return {
        "status": SchedulerStatus.SUCCESS,
        "warnings": warnings,
        "metadata": payload,
    }


def _resolve_trade_date(trade_date: str | None, run_time: str | datetime | None, force: bool) -> tuple[str, bool]:
    base = parse_date(trade_date) if trade_date else parse_date(run_time)
    requested_is_trading = is_trading_day(base)
    if trade_date:
        return base.strftime("%Y-%m-%d"), requested_is_trading
    if requested_is_trading:
        return base.strftime("%Y-%m-%d"), True
    latest = get_latest_trading_day(base)
    return latest.strftime("%Y-%m-%d"), False if not force else is_trading_day(latest)


def run_scheduled_daily_update(
    trade_date: str | None = None,
    run_time: str | datetime | None = None,
    user_ids: list[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
    skip_training: bool = False,
    skip_news: bool = False,
    skip_paper_trading: bool = False,
    source: str = "manual",
    top_k: int = 50,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = AGENT_QUANT_DB_PATH,
    root: str | Path = ".",
    public_task_runner: Callable[..., dict[str, Any]] | None = None,
    user_task_runner: Callable[..., dict[str, Any]] | None = None,
) -> JobStatus:
    started = perf_counter()
    run_time = run_time or datetime.now()
    resolved_trade_date, requested_is_trading = _resolve_trade_date(trade_date, run_time, force=force)
    job = JobStatus(
        job_id=f"daily_update_{resolved_trade_date}",
        run_id=make_run_id(str(source or "manual")),
        trade_date=resolved_trade_date,
        execution_source=str(source or "manual"),
        overall_status=SchedulerStatus.RUNNING,
        is_trading_day=is_trading_day(resolved_trade_date),
    )
    save_job_status(job, root)
    _append_log(resolved_trade_date, f"job started run_id={job.run_id} dry_run={dry_run} force={force}")

    if not requested_is_trading and not force:
        job.overall_status = SchedulerStatus.SKIPPED
        job.finished_at = now_text()
        job.duration_seconds = round(perf_counter() - started, 3)
        job.warnings.append("requested date is not an A-share trading day; skipped.")
        save_job_status(job, root)
        _append_log(resolved_trade_date, "job skipped because requested date is not trading day")
        return job

    lock = JobLock(
        lock_path=Path(root) / "runtime" / "locks" / "daily_update.lock",
        job_id=job.job_id,
        trade_date=resolved_trade_date,
        force=force,
    )
    try:
        with lock:
            public_task_runner = public_task_runner or run_public_daily_tasks
            public_result = run_recorded_step(
                job,
                "public_tasks",
                lambda: public_task_runner(
                    trade_date=resolved_trade_date,
                    output_dir=output_dir,
                    db_path=db_path,
                    force=force,
                    dry_run=dry_run,
                    skip_training=skip_training,
                    skip_news=skip_news,
                    root=root,
                ),
                root=root,
            )
            job.public_task_status = public_result
            meta = public_result.get("metadata") or {}
            job.ranking_output_path = str(meta.get("ranking_output_path") or "")
            job.news_count = int(meta.get("news_event_count") or 0)

            selected_users = user_ids or get_active_user_ids(db_path=db_path, output_dir=output_dir)
            if not selected_users:
                selected_users = ["default"]
                job.warnings.append("no active users found; default user was used for dry scheduler validation.")
            user_task_runner = user_task_runner or run_user_daily_job
            user_results: dict[str, Any] = {}
            for index, user_id in enumerate(selected_users):
                def _run_user(user_id=user_id, sync_legacy=index == 0):
                    return user_task_runner(
                        user_id=user_id,
                        trade_date=resolved_trade_date,
                        output_dir=output_dir,
                        db_path=db_path,
                        top_k=top_k,
                        dry_run=dry_run,
                        skip_news=skip_news,
                        skip_paper_trading=skip_paper_trading,
                        force=force,
                        sync_legacy=sync_legacy,
                        job_id=job.job_id,
                        run_id=job.run_id,
                        execution_source=job.execution_source,
                    )

                result = run_recorded_step(job, f"user:{user_id}", _run_user, root=root, allow_failure=True)
                user_results[str(user_id)] = result
                if result.get("status") == SchedulerStatus.FAILED:
                    continue
                job.recommendation_count += int(result.get("recommendation_count") or 0)
                job.paper_order_count += int(result.get("paper_order_count") or 0)
                job.position_count += int(result.get("position_count") or 0)
                if result.get("report_path"):
                    job.report_path = str(result["report_path"])
            job.user_task_status = user_results
            failed_users = [uid for uid, item in user_results.items() if item.get("status") == SchedulerStatus.FAILED]
            if failed_users:
                job.overall_status = SchedulerStatus.PARTIAL_SUCCESS if len(failed_users) < len(user_results) else SchedulerStatus.FAILED
            else:
                job.overall_status = SchedulerStatus.SUCCESS
    except JobLockError as exc:
        job.overall_status = SchedulerStatus.SKIPPED
        job.failed_steps.append("job_lock")
        job.warnings.append(str(exc))
        _append_log(resolved_trade_date, f"lock skipped: {exc}")
    except Exception as exc:
        job.overall_status = SchedulerStatus.FAILED
        if str(exc) not in job.warnings:
            job.warnings.append(str(exc))
        _append_log(resolved_trade_date, f"job failed: {type(exc).__name__}: {exc}")
    finally:
        job.finished_at = now_text()
        job.duration_seconds = round(perf_counter() - started, 3)
        save_job_status(job, root)
        _append_log(resolved_trade_date, f"job finished status={job.overall_status}")
    return job
