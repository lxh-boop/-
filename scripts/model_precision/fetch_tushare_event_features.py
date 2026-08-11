from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_tushare import get_token, init_tushare_pro, to_ts_code


DEFAULT_PREDICTION_HISTORY = (
    ROOT
    / "outputs"
    / "backtests"
    / "predictions"
    / "target_full_recent_v1_kronos_mini_t1_predictions.csv"
)
DEFAULT_OUTPUT_DIR = ROOT / "data" / "model_precision" / "tushare_events"
STOCK_ENDPOINTS = (
    "fina_indicator",
    "forecast",
    "express",
    "dividend",
    "stk_holdernumber",
    "share_float",
)
DATE_ENDPOINTS = ("top_list", "block_trade", "top_inst", "repurchase")
MONTH_ENDPOINTS = ("broker_recommend",)


class RequestRateLimiter:
    def __init__(self, minimum_interval_seconds: float) -> None:
        self.minimum_interval_seconds = max(float(minimum_interval_seconds), 0.0)
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_allowed - now)
            self._next_allowed = max(now, self._next_allowed) + self.minimum_interval_seconds
        if delay:
            time.sleep(delay)


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    os.replace(temporary, path)


def _atomic_json(payload: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _call_with_retry(
    call: Callable[[], pd.DataFrame],
    *,
    limiter: RequestRateLimiter,
    retries: int,
) -> pd.DataFrame:
    error: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            limiter.wait()
            result = call()
            return pd.DataFrame() if result is None else result.copy()
        except Exception as exc:
            error = exc
            if attempt + 1 < retries:
                time.sleep(min(8.0, 1.5 * (2**attempt)))
    assert error is not None
    raise RuntimeError(type(error).__name__) from error


def _read_universe(path: Path) -> tuple[list[str], list[str]]:
    frame = pd.read_csv(path, dtype={"code": str}, usecols=["date", "code"])
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    codes = sorted(
        {
            str(value).split(".")[0].zfill(6)
            for value in frame["code"].dropna().astype(str)
        }
    )
    dates = sorted(frame["date"].dropna().dt.strftime("%Y%m%d").unique().tolist())
    if not codes or not dates:
        raise RuntimeError("prediction history does not contain a usable universe")
    return codes, dates


def _cached(path: Path) -> bool:
    meta = path.with_suffix(".meta.json")
    if not meta.exists():
        return False
    try:
        return json.loads(meta.read_text(encoding="utf-8")).get("complete") is True
    except Exception:
        return False


def _stock_call(
    client,
    endpoint: str,
    *,
    ts_code: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    method = getattr(client, endpoint)
    if endpoint == "dividend":
        frame = method(ts_code=ts_code)
    else:
        frame = method(ts_code=ts_code, start_date=start_date, end_date=end_date)
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame
    causal_date = "ann_date" if "ann_date" in frame.columns else "end_date"
    if causal_date in frame.columns:
        values = frame[causal_date].astype(str).str.replace("-", "", regex=False)
        frame = frame[values.between(start_date, end_date)]
    return frame


def _date_call(client, endpoint: str, trade_date: str) -> pd.DataFrame:
    if endpoint == "repurchase":
        return client.repurchase(ann_date=trade_date)
    return getattr(client, endpoint)(trade_date=trade_date)


def _month_call(client, endpoint: str, month: str) -> pd.DataFrame:
    return getattr(client, endpoint)(month=month)


def _download_items(
    *,
    endpoint: str,
    items: list[str],
    cache_dir: Path,
    fetch: Callable[[object, str], pd.DataFrame],
    token: str,
    workers: int,
    minimum_interval_seconds: float,
    retries: int,
) -> dict[str, object]:
    endpoint_dir = cache_dir / endpoint
    endpoint_dir.mkdir(parents=True, exist_ok=True)
    pending = [item for item in items if not _cached(endpoint_dir / f"{item}.csv")]
    print(
        f"[{endpoint}] total={len(items)} cached={len(items)-len(pending)} "
        f"pending={len(pending)}",
        flush=True,
    )
    limiter = RequestRateLimiter(minimum_interval_seconds)
    local = threading.local()
    failures: dict[str, str] = {}
    completed = 0

    def task(item: str) -> tuple[str, int]:
        client = getattr(local, "client", None)
        if client is None:
            client = init_tushare_pro(token)
            local.client = client
        frame = _call_with_retry(
            lambda: fetch(client, item), limiter=limiter, retries=retries
        )
        path = endpoint_dir / f"{item}.csv"
        _atomic_csv(frame, path)
        _atomic_json(
            {"complete": True, "rows": int(len(frame)), "updated_at": datetime.now().isoformat(timespec="seconds")},
            path.with_suffix(".meta.json"),
        )
        return item, int(len(frame))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(task, item): item for item in pending}
        for future in as_completed(futures):
            item = futures[future]
            succeeded = False
            try:
                future.result()
                completed += 1
                succeeded = True
            except Exception as exc:
                failures[item] = type(exc).__name__
            if succeeded and completed % 200 == 0:
                print(f"[{endpoint}] completed={completed}/{len(pending)}", flush=True)

    frames = []
    for item in items:
        path = endpoint_dir / f"{item}.csv"
        if path.exists() and path.stat().st_size:
            try:
                frame = pd.read_csv(path, dtype=str)
            except pd.errors.EmptyDataError:
                continue
            if not frame.empty:
                frames.append(frame)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    output_path = cache_dir / f"{endpoint}.csv"
    _atomic_csv(combined, output_path)
    return {
        "endpoint": endpoint,
        "items": len(items),
        "rows": int(len(combined)),
        "failures": failures,
        "output": str(output_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download causal Tushare stock-event features for Top15 modeling."
    )
    parser.add_argument("--prediction-history", type=Path, default=DEFAULT_PREDICTION_HISTORY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--start-date", default="20180101")
    parser.add_argument("--end-date", default="20260810")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--minimum-interval", type=float, default=0.12)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--stock-endpoints", nargs="*", default=list(STOCK_ENDPOINTS))
    parser.add_argument("--date-endpoints", nargs="*", default=list(DATE_ENDPOINTS))
    parser.add_argument("--month-endpoints", nargs="*", default=list(MONTH_ENDPOINTS))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    invalid = set(args.stock_endpoints).difference(STOCK_ENDPOINTS)
    invalid.update(set(args.date_endpoints).difference(DATE_ENDPOINTS))
    invalid.update(set(args.month_endpoints).difference(MONTH_ENDPOINTS))
    if invalid:
        raise ValueError(f"unsupported endpoints: {sorted(invalid)}")
    token = get_token()
    codes, dates = _read_universe(args.prediction_history)
    dates = [date for date in dates if args.start_date <= date <= args.end_date]
    reports = []
    for endpoint in args.stock_endpoints:
        reports.append(
            _download_items(
                endpoint=endpoint,
                items=codes,
                cache_dir=args.output_dir,
                fetch=lambda client, code, name=endpoint: _stock_call(
                    client,
                    name,
                    ts_code=to_ts_code(code),
                    start_date=args.start_date,
                    end_date=args.end_date,
                ),
                token=token,
                workers=args.workers,
                minimum_interval_seconds=args.minimum_interval,
                retries=args.retries,
            )
        )
    for endpoint in args.date_endpoints:
        reports.append(
            _download_items(
                endpoint=endpoint,
                items=dates,
                cache_dir=args.output_dir,
                fetch=lambda client, date, name=endpoint: _date_call(client, name, date),
                token=token,
                workers=args.workers,
                minimum_interval_seconds=args.minimum_interval,
                retries=args.retries,
            )
        )
    months = sorted({date[:6] for date in dates})
    for endpoint in args.month_endpoints:
        reports.append(
            _download_items(
                endpoint=endpoint,
                items=months,
                cache_dir=args.output_dir,
                fetch=lambda client, month, name=endpoint: _month_call(
                    client, name, month
                ),
                token=token,
                workers=args.workers,
                minimum_interval_seconds=args.minimum_interval,
                retries=args.retries,
            )
        )
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "stock_count": len(codes),
        "trade_date_count": len(dates),
        "reports": reports,
        "token_persisted": False,
    }
    _atomic_json(manifest, args.output_dir / "manifest.json")
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    return 0 if not any(report["failures"] for report in reports) else 2


if __name__ == "__main__":
    raise SystemExit(main())
