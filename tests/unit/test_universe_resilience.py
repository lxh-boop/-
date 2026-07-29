from __future__ import annotations

import sys
import types
from datetime import datetime

import pandas as pd

import universe


def _constituents(
    *,
    count: int = 300,
    trade_date: str = "20260630",
    index_code: str = "000300.SH",
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "index_code": [index_code] * count,
            "con_code": [
                f"{index_value:06d}.SZ"
                for index_value in range(1, count + 1)
            ],
            "trade_date": [trade_date] * count,
            "weight": [1.0] * count,
        }
    )


def test_tushare_index_weight_queries_month_by_month(
    monkeypatch,
    tmp_path,
) -> None:
    calls: list[dict[str, str]] = []

    class FakePro:
        def index_weight(self, **kwargs):
            calls.append(kwargs)
            if kwargs["start_date"].startswith("202607"):
                return pd.DataFrame()
            return _constituents(
                trade_date="20260630",
                index_code=kwargs["index_code"],
            )

        def stock_basic(self, **kwargs):
            return pd.DataFrame()

    fake_tushare = types.SimpleNamespace(
        set_token=lambda token: None,
        pro_api=lambda token=None: FakePro(),
    )
    monkeypatch.setitem(sys.modules, "tushare", fake_tushare)
    monkeypatch.setattr(universe, "CSI300_INDEX_WEIGHT_LOOKBACK_MONTHS", 3)
    monkeypatch.setattr(
        universe,
        "CSI300_POOL_CACHE_PATH",
        str(tmp_path / "csi300.csv"),
    )
    monkeypatch.setattr(
        universe,
        "CSI300_POOL_LAST_GOOD_PATH",
        str(tmp_path / "csi300.last_good.csv"),
    )
    monkeypatch.setattr(
        universe,
        "datetime",
        type(
            "FixedDatetime",
            (datetime,),
            {
                "today": classmethod(
                    lambda cls: cls(2026, 7, 28)
                ),
            },
        ),
    )

    pool = universe.read_csi300_from_tushare_index_weight("token")

    assert len(pool) == 300
    assert calls[0]["start_date"] == "20260701"
    assert calls[0]["end_date"] == "20260731"
    assert any(
        call["start_date"] == "20260601"
        and call["end_date"] == "20260630"
        for call in calls
    )
    assert (tmp_path / "csi300.csv").is_file()
    assert (tmp_path / "csi300.last_good.csv").is_file()


def test_get_stock_pool_uses_akshare_when_tushare_fails(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        universe,
        "CSI300_POOL_CACHE_PATH",
        str(tmp_path / "missing.csv"),
    )
    monkeypatch.setattr(
        universe,
        "CSI300_POOL_LAST_GOOD_PATH",
        str(tmp_path / "missing.last_good.csv"),
    )
    monkeypatch.setattr(universe, "UNIVERSE", "csi300")
    monkeypatch.setattr(
        universe,
        "read_csi300_from_qlib_instruments",
        lambda: (_ for _ in ()).throw(RuntimeError("qlib missing")),
    )
    monkeypatch.setattr(
        universe,
        "read_csi300_from_tushare_index_weight",
        lambda token: (_ for _ in ()).throw(
            RuntimeError("permission denied")
        ),
    )
    monkeypatch.setattr(
        universe,
        "read_csi300_from_akshare",
        lambda: {
            f"{index_value:06d}": f"N{index_value}"
            for index_value in range(1, 301)
        },
    )
    monkeypatch.setattr(universe, "CSI300_AKSHARE_FALLBACK_ENABLED", True)
    monkeypatch.setattr(universe, "USE_TUSHARE_INDEX_WEIGHT_FALLBACK", True)

    pool = universe.get_stock_pool(token="token")

    assert len(pool) == 300
    assert pool["000001"] == "N1"


def test_get_stock_pool_uses_stale_last_good_after_refresh_failure(
    monkeypatch,
    tmp_path,
) -> None:
    cache_path = tmp_path / "csi300.csv"
    last_good_path = tmp_path / "csi300.last_good.csv"
    frame = pd.DataFrame(
        {
            "code": [
                f"{index_value:06d}"
                for index_value in range(1, 301)
            ],
            "ts_code": [
                f"{index_value:06d}.SZ"
                for index_value in range(1, 301)
            ],
            "name": [
                f"N{index_value}"
                for index_value in range(1, 301)
            ],
            "source": ["test"] * 300,
        }
    )
    frame.to_csv(last_good_path, index=False, encoding="utf-8-sig")

    monkeypatch.setattr(universe, "CSI300_POOL_CACHE_PATH", str(cache_path))
    monkeypatch.setattr(
        universe,
        "CSI300_POOL_LAST_GOOD_PATH",
        str(last_good_path),
    )
    monkeypatch.setattr(universe, "UNIVERSE", "csi300")
    monkeypatch.setattr(
        universe,
        "read_csi300_from_qlib_instruments",
        lambda: (_ for _ in ()).throw(RuntimeError("qlib missing")),
    )
    monkeypatch.setattr(
        universe,
        "read_csi300_from_tushare_index_weight",
        lambda token: (_ for _ in ()).throw(RuntimeError("tushare empty")),
    )
    monkeypatch.setattr(
        universe,
        "read_csi300_from_akshare",
        lambda: (_ for _ in ()).throw(RuntimeError("akshare offline")),
    )
    monkeypatch.setattr(universe, "CSI300_AKSHARE_FALLBACK_ENABLED", True)
    monkeypatch.setattr(universe, "USE_TUSHARE_INDEX_WEIGHT_FALLBACK", True)

    pool = universe.get_stock_pool(token="token")

    assert len(pool) == 300
    assert pool["000001"] == "N1"


def test_invalid_cache_never_replaces_last_good(
    monkeypatch,
    tmp_path,
) -> None:
    current_path = tmp_path / "csi300.csv"
    last_good_path = tmp_path / "csi300.last_good.csv"

    valid = pd.DataFrame(
        {
            "code": [
                f"{index_value:06d}"
                for index_value in range(1, 301)
            ],
            "name": [
                f"N{index_value}"
                for index_value in range(1, 301)
            ],
        }
    )
    monkeypatch.setattr(
        universe,
        "CSI300_POOL_CACHE_PATH",
        str(current_path),
    )
    monkeypatch.setattr(
        universe,
        "CSI300_POOL_LAST_GOOD_PATH",
        str(last_good_path),
    )

    normalized = universe._normalize_pool_frame(
        valid,
        source="test",
        effective_date="2026-06-30",
    )
    universe._save_pool_cache(normalized)
    before = last_good_path.read_bytes()

    invalid = pd.DataFrame(
        {
            "code": ["000001", "000002"],
            "name": ["A", "B"],
        }
    )
    try:
        universe._normalize_pool_frame(
            invalid,
            source="invalid",
            effective_date="2026-07-01",
        )
    except ValueError:
        pass

    assert last_good_path.read_bytes() == before
