from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from database.repositories import NewsRepository
from scoring.schemas import NewsEvidenceSignal


@dataclass(frozen=True)
class HistoricalNewsResult:
    trade_date: str
    status: str = "missing_or_incomplete"
    evidence: list[NewsEvidenceSignal] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _parse_time(value: str) -> datetime | None:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d %H:%M:%S", "%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(datetime.now().strftime(fmt))], fmt)
        except Exception:
            continue
    return None


def load_historical_news(
    trade_date: str,
    stock_codes: list[str],
    db_path: str | Path | None = None,
    decision_time: str | None = None,
) -> HistoricalNewsResult:
    decision_time = decision_time or f"{trade_date} 15:00:00"
    decision_dt = _parse_time(decision_time)
    evidence: list[NewsEvidenceSignal] = []
    warnings: list[str] = []
    try:
        repo = NewsRepository(db_path)
        for code in stock_codes:
            for row in repo.list_news_stock_mappings(stock_code=code):
                news_id = str(row.get("news_id") or "")
                event = repo.get_news_event(news_id) if news_id else None
                merged = {**(event or {}), **row}
                publish_dt = _parse_time(str(merged.get("publish_time") or ""))
                assigned_trade_date = str(merged.get("trade_date") or "")
                if assigned_trade_date and assigned_trade_date > trade_date:
                    continue
                if publish_dt and decision_dt and publish_dt > decision_dt:
                    continue
                signal = NewsEvidenceSignal.from_mapping(merged)
                evidence.append(signal)
    except Exception as exc:
        warnings.append(f"failed to load historical news for {trade_date}: {exc}")

    if not evidence:
        warnings.append("historical news missing or incomplete; news adjustment remains neutral.")
        return HistoricalNewsResult(trade_date=trade_date, status="missing_or_incomplete", warnings=warnings)
    return HistoricalNewsResult(trade_date=trade_date, status="success", evidence=evidence, warnings=warnings)
