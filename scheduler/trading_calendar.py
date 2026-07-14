from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Iterable

try:
    from config import QLIB_PROVIDER_URI
except Exception:
    QLIB_PROVIDER_URI = r"D:\qlib_data\cn_data"


# Static fallback for common A-share full-market holidays. Qlib calendar is
# preferred whenever the requested date is inside the available calendar range.
CN_MARKET_HOLIDAYS = {
    "2025-01-01",
    "2025-01-28",
    "2025-01-29",
    "2025-01-30",
    "2025-01-31",
    "2025-02-03",
    "2025-02-04",
    "2025-04-04",
    "2025-05-01",
    "2025-05-02",
    "2025-05-05",
    "2025-06-02",
    "2025-10-01",
    "2025-10-02",
    "2025-10-03",
    "2025-10-06",
    "2025-10-07",
    "2025-10-08",
    "2026-01-01",
    "2026-02-16",
    "2026-02-17",
    "2026-02-18",
    "2026-02-19",
    "2026-02-20",
    "2026-02-23",
    "2026-04-06",
    "2026-05-01",
    "2026-05-04",
    "2026-05-05",
    "2026-06-19",
    "2026-09-25",
    "2026-10-01",
    "2026-10-02",
    "2026-10-05",
    "2026-10-06",
    "2026-10-07",
}


def parse_date(value: str | date | datetime | None) -> date:
    if value is None:
        return datetime.now().date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            candidate = text[:8] if fmt == "%Y%m%d" else text[:10]
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"invalid date: {value}")


def _calendar_paths() -> Iterable[Path]:
    provider = Path(str(QLIB_PROVIDER_URI))
    yield provider / "calendars" / "day.txt"
    yield Path("data") / "trading_calendar.csv"


@lru_cache(maxsize=1)
def _qlib_calendar() -> tuple[set[date], date | None, date | None]:
    values: set[date] = set()
    for path in _calendar_paths():
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            text = line.strip().split(",")[0]
            if not text or text.lower() in {"date", "datetime"}:
                continue
            try:
                values.add(parse_date(text))
            except Exception:
                continue
        if values:
            break
    if not values:
        return set(), None, None
    return values, min(values), max(values)


def _fallback_is_trading_day(value: date) -> bool:
    if value.weekday() >= 5:
        return False
    if value.strftime("%Y-%m-%d") in CN_MARKET_HOLIDAYS:
        return False
    return True


def is_trading_day(date_value: str | date | datetime | None) -> bool:
    value = parse_date(date_value)
    calendar, min_day, max_day = _qlib_calendar()
    if calendar and min_day and max_day and min_day <= value <= max_day:
        return value in calendar
    return _fallback_is_trading_day(value)


def get_latest_trading_day(date_value: str | date | datetime | None) -> date:
    value = parse_date(date_value)
    for offset in range(0, 370):
        candidate = value - timedelta(days=offset)
        if is_trading_day(candidate):
            return candidate
    raise RuntimeError(f"failed to find latest trading day before {value}")


def get_next_trading_day(date_value: str | date | datetime | None) -> date:
    value = parse_date(date_value)
    for offset in range(1, 370):
        candidate = value + timedelta(days=offset)
        if is_trading_day(candidate):
            return candidate
    raise RuntimeError(f"failed to find next trading day after {value}")
