from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_SEARCH_DIRS = (
    "results",
    "outputs",
    "data",
    "models",
    "records",
    "mlruns",
    "qlib",
    "backtest",
    "predictions",
    "rankings",
    "reports",
)

PREDICTION_HINTS = ("pred", "prediction", "score", "rank", "signal")
BACKTEST_HINTS = ("position", "order", "trade", "portfolio", "daily_return", "account", "nav", "benchmark")


@dataclass(frozen=True)
class HistoricalDataAudit:
    start_date: str
    end_date: str
    prediction_files: list[str] = field(default_factory=list)
    backtest_files: list[str] = field(default_factory=list)
    coverage_start_date: str = ""
    coverage_end_date: str = ""
    stock_pool: str = ""
    model_name: str = ""
    daily_stock_count: float = 0.0
    has_score: bool = False
    has_rank: bool = False
    has_price: bool = False
    has_positions: bool = False
    has_trades: bool = False
    has_daily_return: bool = False
    has_future_leakage_risk: bool = False
    selected_source: str = ""
    imported_ranking_dates: int = 0
    restored_holding_dates: int = 0
    true_hold_days: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HistoricalSignalImportResult:
    status: str
    source_path: str
    output_dir: str
    start_date: str
    end_date: str
    imported_ranking_dates: int = 0
    imported_rows: int = 0
    restored_holding_dates: int = 0
    output_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _date_token(value: Any) -> str:
    text = str(value or "").replace("-", "")[:8]
    return text if len(text) == 8 and text.isdigit() else ""


def _date_text(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.strftime("%Y-%m-%d")


def _stock_code(value: Any) -> str:
    text = str(value or "").strip().split(".")[0]
    if not text or text.lower() == "nan":
        return ""
    return text.zfill(6)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except Exception:
        return default


def _read_csv_columns(path: Path) -> list[str]:
    try:
        return list(pd.read_csv(path, nrows=0).columns)
    except Exception:
        return []


def _iter_candidate_files(search_dirs: list[str | Path] | None = None) -> list[Path]:
    roots = [Path(item) for item in (search_dirs or DEFAULT_SEARCH_DIRS)]
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".csv", ".json", ".pkl", ".parquet"}:
                files.append(path)
    return sorted(set(files))


def _is_prediction_file(path: Path, columns: list[str]) -> bool:
    names = {col.lower() for col in columns}
    has_date = bool(names & {"trade_date", "date", "datetime", "signal_date"})
    has_code = bool(names & {"stock_code", "code", "instrument", "symbol"})
    has_score = bool(names & {"score", "pred_score", "pred_5d_ret", "prediction", "raw_score"})
    return has_date and has_code and has_score and any(hint in path.name.lower() for hint in PREDICTION_HINTS)


def _is_backtest_file(path: Path, columns: list[str]) -> bool:
    names = {col.lower() for col in columns}
    return bool(
        names
        & {
            "positions",
            "selected_codes",
            "orders",
            "trades",
            "daily_return",
            "net_return",
            "portfolio_ret",
            "account_value",
            "nav",
            "benchmark_return",
        }
    ) or any(hint in path.name.lower() for hint in BACKTEST_HINTS)


def _load_frame(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".pkl":
        return pd.read_pickle(path)
    if path.suffix.lower() == ".json":
        return pd.read_json(path)
    return pd.read_csv(path, dtype={"code": str, "stock_code": str, "instrument": str}, encoding="utf-8-sig")


def _date_column(df: pd.DataFrame) -> str:
    for column in ["trade_date", "date", "datetime", "signal_date"]:
        if column in df.columns:
            return column
    return ""


def _code_column(df: pd.DataFrame) -> str:
    for column in ["stock_code", "code", "instrument", "symbol"]:
        if column in df.columns:
            return column
    return ""


def _score_column(df: pd.DataFrame) -> str:
    for column in ["score", "pred_score", "pred_5d_ret", "prediction", "raw_score"]:
        if column in df.columns:
            return column
    return ""


def _price_column(df: pd.DataFrame) -> str:
    for column in ["current_price", "close", "price"]:
        if column in df.columns:
            return column
    return ""


def _select_source(prediction_files: list[str], start_date: str, end_date: str) -> str:
    preferred = Path("outputs") / "backtest_daily_predictions.csv"
    if str(preferred) in prediction_files or str(preferred.resolve()) in prediction_files:
        return str(preferred)
    scored: list[tuple[int, int, str]] = []
    for file in prediction_files:
        try:
            df = _load_frame(file)
            date_col = _date_column(df)
            if not date_col:
                continue
            dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
            if dates.empty:
                continue
            coverage = int((dates.min() <= pd.Timestamp(start_date)) and (dates.max() >= pd.Timestamp(end_date)))
            scored.append((coverage, len(df), file))
        except Exception:
            continue
    if not scored:
        return ""
    return sorted(scored, reverse=True)[0][2]


def audit_historical_signals(
    start_date: str,
    end_date: str,
    search_dirs: list[str | Path] | None = None,
    output_dir: str | Path = "outputs",
) -> HistoricalDataAudit:
    prediction_files: list[str] = []
    backtest_files: list[str] = []
    has_positions = False
    has_trades = False
    has_daily_return = False
    for path in _iter_candidate_files(search_dirs):
        columns = _read_csv_columns(path) if path.suffix.lower() == ".csv" else []
        if _is_prediction_file(path, columns):
            prediction_files.append(str(path))
        if _is_backtest_file(path, columns):
            backtest_files.append(str(path))
            lower = path.name.lower()
            names = {col.lower() for col in columns}
            has_positions = has_positions or "position" in lower or "positions" in names or "selected_codes" in names
            has_trades = has_trades or "trade" in lower or bool(names & {"trade_date", "rebalance_action"})
            has_daily_return = has_daily_return or bool(names & {"daily_return", "net_return", "portfolio_ret", "nav"})

    selected = _select_source(prediction_files, start_date, end_date)
    coverage_start = ""
    coverage_end = ""
    stock_pool = ""
    model_name = ""
    daily_stock_count = 0.0
    has_score = False
    has_rank = False
    has_price = False
    leakage = False
    if selected:
        df = _load_frame(selected)
        date_col = _date_column(df)
        code_col = _code_column(df)
        score_col = _score_column(df)
        price_col = _price_column(df)
        if date_col:
            dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
            if not dates.empty:
                coverage_start = dates.min().strftime("%Y-%m-%d")
                coverage_end = dates.max().strftime("%Y-%m-%d")
                daily_stock_count = float(df.groupby(pd.to_datetime(df[date_col], errors="coerce").dt.strftime("%Y-%m-%d")).size().median())
        if code_col:
            stock_pool = f"{df[code_col].astype(str).nunique()} stocks"
        if "model_name" in df.columns and not df["model_name"].dropna().empty:
            model_name = str(df["model_name"].dropna().iloc[0])
        has_score = bool(score_col)
        has_rank = "rank" in df.columns or "pred_rank" in df.columns or "original_rank" in df.columns
        has_price = bool(price_col)
        leakage = "future_5d_ret" in df.columns or "future_1d_ret" in df.columns

    result = HistoricalDataAudit(
        start_date=start_date,
        end_date=end_date,
        prediction_files=prediction_files,
        backtest_files=backtest_files,
        coverage_start_date=coverage_start,
        coverage_end_date=coverage_end,
        stock_pool=stock_pool,
        model_name=model_name,
        daily_stock_count=daily_stock_count,
        has_score=has_score,
        has_rank=has_rank,
        has_price=has_price,
        has_positions=has_positions,
        has_trades=has_trades,
        has_daily_return=has_daily_return,
        has_future_leakage_risk=leakage,
        selected_source=selected,
    )
    out = Path(output_dir) / "historical_signal_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _normalise_prediction_frame(df: pd.DataFrame, start_date: str, end_date: str, model_name: str = "") -> pd.DataFrame:
    date_col = _date_column(df)
    code_col = _code_column(df)
    score_col = _score_column(df)
    price_col = _price_column(df)
    if not date_col or not code_col or not score_col:
        raise ValueError("source must contain date, stock code, and score columns")
    data = df.copy()
    data["trade_date"] = pd.to_datetime(data[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
    data = data[(data["trade_date"] >= start_date) & (data["trade_date"] <= end_date)].copy()
    data["stock_code"] = data[code_col].map(_stock_code)
    data["stock_name"] = data.get("stock_name", data.get("name", ""))
    data["original_score"] = pd.to_numeric(data[score_col], errors="coerce").fillna(0.0)
    data["current_price"] = pd.to_numeric(data[price_col], errors="coerce") if price_col else 0.0
    if model_name:
        data["model_name"] = model_name
    elif "model_name" in data.columns:
        data["model_name"] = data["model_name"].astype(str)
    else:
        data["model_name"] = "historical_backtest"
    if "model_version" in data.columns:
        data["model_version"] = data["model_version"].astype(str)
    elif "model_backend" in data.columns:
        data["model_version"] = data["model_backend"].astype(str)
    else:
        data["model_version"] = ""
    data["source"] = "historical_backtest_prediction"
    data = data[data["stock_code"] != ""].copy()
    data = data.sort_values(["trade_date", "original_score", "stock_code"], ascending=[True, False, True])
    data["original_rank"] = data.groupby("trade_date").cumcount() + 1
    if "rank" in df.columns:
        data["original_rank"] = pd.to_numeric(df.loc[data.index, "rank"], errors="coerce").fillna(data["original_rank"]).astype(int)
    for src, dst in [
        ("pred_score", "pred_score"),
        ("pred_5d_ret", "pred_5d_ret"),
        ("up_prob", "up_prob"),
        ("ret_5", "ret_5"),
        ("ret_20", "ret_20"),
        ("vol_20", "vol_20"),
        ("drawdown_20", "drawdown_20"),
    ]:
        data[dst] = data[src] if src in data.columns else ""
    if "pred_score" not in df.columns:
        data["pred_score"] = data["original_score"]
    data["score"] = data["original_score"]
    data["pred_rank"] = data["original_rank"]
    data["rank"] = data["original_rank"]
    data["close"] = data["current_price"]
    data["code"] = data["stock_code"]
    data["name"] = data["stock_name"]
    columns = [
        "stock_code",
        "stock_name",
        "trade_date",
        "original_score",
        "original_rank",
        "current_price",
        "model_name",
        "model_version",
        "source",
        "pred_score",
        "score",
        "pred_rank",
        "rank",
        "close",
        "code",
        "name",
        "pred_5d_ret",
        "up_prob",
        "ret_5",
        "ret_20",
        "vol_20",
        "drawdown_20",
    ]
    return data[columns]


def import_historical_signals(
    source_path: str | Path,
    start_date: str,
    end_date: str,
    universe: str = "csi300",
    model_name: str = "historical_backtest",
    output_dir: str | Path = "outputs",
) -> HistoricalSignalImportResult:
    del universe
    warnings: list[str] = []
    source = Path(source_path)
    df = _load_frame(source)
    normalised = _normalise_prediction_frame(df, start_date, end_date, model_name=model_name)
    out_root = Path(output_dir) / "rankings" / "history"
    out_root.mkdir(parents=True, exist_ok=True)
    output_files: list[str] = []
    imported_rows = 0
    for trade_date, group in normalised.groupby("trade_date", sort=True):
        if not trade_date:
            continue
        token = _date_token(trade_date)
        if not token:
            continue
        path = out_root / f"ranking_{token}.csv"
        group.sort_values("original_rank").to_csv(path, index=False, encoding="utf-8-sig")
        output_files.append(str(path))
        imported_rows += len(group)
    if not output_files:
        warnings.append("no historical ranking dates imported")
    return HistoricalSignalImportResult(
        status="success" if output_files else "empty",
        source_path=str(source),
        output_dir=str(out_root),
        start_date=start_date,
        end_date=end_date,
        imported_ranking_dates=len(output_files),
        imported_rows=imported_rows,
        output_files=output_files,
        warnings=warnings,
    )


def import_historical_holdings(
    source_path: str | Path,
    start_date: str,
    end_date: str,
    output_dir: str | Path = "outputs",
) -> HistoricalSignalImportResult:
    source = Path(source_path)
    df = _load_frame(source)
    date_col = _date_column(df)
    code_col = _code_column(df)
    if not date_col or not code_col:
        raise ValueError("holding source must contain date and stock code columns")
    data = df.copy()
    data["trade_date"] = pd.to_datetime(data[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
    data = data[(data["trade_date"] >= start_date) & (data["trade_date"] <= end_date)].copy()
    data["stock_code"] = data[code_col].map(_stock_code)
    data["source"] = "historical_backtest_holdings"
    out_root = Path(output_dir) / "rankings" / "history"
    out_root.mkdir(parents=True, exist_ok=True)
    output_files: list[str] = []
    for trade_date, group in data.groupby("trade_date", sort=True):
        token = _date_token(trade_date)
        path = out_root / f"holdings_{token}.csv"
        group.to_csv(path, index=False, encoding="utf-8-sig")
        output_files.append(str(path))
    return HistoricalSignalImportResult(
        status="success" if output_files else "empty",
        source_path=str(source),
        output_dir=str(out_root),
        start_date=start_date,
        end_date=end_date,
        restored_holding_dates=len(output_files),
        output_files=output_files,
    )


@lru_cache(maxsize=16)
def _price_frame(path_text: str) -> pd.DataFrame:
    path = Path(path_text)
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, dtype={"code": str, "stock_code": str}, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()
    date_col = _date_column(df)
    code_col = _code_column(df)
    price_col = _price_column(df)
    if not date_col or not code_col or not price_col:
        return pd.DataFrame()
    result = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(df[date_col], errors="coerce").dt.strftime("%Y-%m-%d"),
            "stock_code": df[code_col].map(_stock_code),
            "close": pd.to_numeric(df[price_col], errors="coerce"),
        }
    )
    return result.dropna(subset=["trade_date", "close"])


def _price_sources(output_dir: str | Path = "outputs") -> list[Path]:
    root = Path(output_dir)
    paths = [
        root / "backtest_daily_predictions.csv",
        root / "backtest_trades.csv",
        Path("data") / "latest_raw_stock_data.csv",
        Path("data") / "raw_stock_data.csv",
    ]
    history = root / "rankings" / "history"
    if history.exists():
        paths.extend(sorted(history.glob("ranking_*.csv")))
    return [path for path in paths if path.exists()]


def get_historical_close(
    stock_code: str,
    trade_date: str,
    output_dir: str | Path = "outputs",
    allow_forward_fill: bool = True,
) -> float | None:
    code = _stock_code(stock_code)
    target = _date_text(trade_date)
    if not code or not target:
        return None
    best_date = ""
    best_price: float | None = None
    for path in _price_sources(output_dir):
        df = _price_frame(str(path.resolve()))
        if df.empty:
            continue
        matched = df[df["stock_code"] == code]
        if matched.empty:
            continue
        exact = matched[matched["trade_date"] == target]
        if not exact.empty:
            price = _safe_float(exact.iloc[-1]["close"], 0.0)
            if price > 0:
                return price
        if allow_forward_fill:
            prior = matched[matched["trade_date"] <= target].sort_values("trade_date")
            if not prior.empty:
                row = prior.iloc[-1]
                price = _safe_float(row["close"], 0.0)
                date_text = str(row["trade_date"])
                if price > 0 and date_text >= best_date:
                    best_date = date_text
                    best_price = price
    return best_price


def get_historical_price_lookup(
    stock_codes: list[str],
    trade_date: str,
    output_dir: str | Path = "outputs",
) -> dict[str, float]:
    lookup: dict[str, float] = {}
    for code in stock_codes:
        price = get_historical_close(code, trade_date, output_dir=output_dir)
        if price and price > 0:
            lookup[_stock_code(code)] = price
    return lookup


def _print_result(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit or import historical backtest signals")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["audit", "import"]:
        cmd = sub.add_parser(name)
        cmd.add_argument("--start-date", required=True)
        cmd.add_argument("--end-date", required=True)
        cmd.add_argument("--source-path", default="")
        cmd.add_argument("--output-dir", default="outputs")
        cmd.add_argument("--universe", default="csi300")
        cmd.add_argument("--model-name", default="historical_backtest")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "audit":
        result = audit_historical_signals(args.start_date, args.end_date, output_dir=args.output_dir)
        _print_result(result.to_dict())
        return 0
    audit = audit_historical_signals(args.start_date, args.end_date, output_dir=args.output_dir)
    source = args.source_path or audit.selected_source
    if not source:
        _print_result({"status": "failed", "error": "no historical prediction source found", "audit": audit.to_dict()})
        return 1
    result = import_historical_signals(
        source,
        start_date=args.start_date,
        end_date=args.end_date,
        universe=args.universe,
        model_name=args.model_name,
        output_dir=args.output_dir,
    )
    _print_result({**result.to_dict(), "audit": audit.to_dict()})
    return 0 if result.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
