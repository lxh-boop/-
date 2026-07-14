from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.tools._common import portfolio_user_dir, safe_float
from portfolio.storage import PortfolioStorage


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if isinstance(value, dict):
        return dict(value)
    return {}


def _source(label: str, path: Path) -> dict[str, Any]:
    return {"label": label, "path": str(path), "exists": path.exists()}


def _active_positions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if safe_float(row.get("quantity"), 0.0) > 0.0]


class AccountRepository:
    def load_account(
        self,
        user_id: str,
        *,
        output_dir: str | Path = "outputs",
        db_path: str | Path | None = None,
    ) -> Any:
        storage = PortfolioStorage(db_path, output_dir=portfolio_user_dir(output_dir, user_id))
        return storage.load_account(f"paper_{user_id}")

    def load_historical_account_snapshot(
        self,
        user_id: str,
        trade_date: str,
        *,
        output_dir: str | Path = "outputs",
        db_path: str | Path | None = None,
    ) -> dict[str, Any]:
        storage = PortfolioStorage(db_path, output_dir=portfolio_user_dir(output_dir, user_id))
        token = "".join(char for char in str(trade_date or "") if char.isdigit())[:8]
        if not token:
            return {}
        history_dir = storage.output_dir / "history" / "accounts"
        candidates = []
        if history_dir.exists():
            candidates = sorted(history_dir.glob(f"account_{token}*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in candidates:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
        return {}


class PortfolioRepository:
    def load_positions(
        self,
        user_id: str,
        *,
        output_dir: str | Path = "outputs",
        db_path: str | Path | None = None,
    ) -> list[Any]:
        storage = PortfolioStorage(db_path, output_dir=portfolio_user_dir(output_dir, user_id))
        return storage.load_positions(user_id)


class OrderRepository:
    def load_orders(
        self,
        user_id: str,
        *,
        output_dir: str | Path = "outputs",
        db_path: str | Path | None = None,
    ) -> list[Any]:
        storage = PortfolioStorage(db_path, output_dir=portfolio_user_dir(output_dir, user_id))
        return storage.load_orders(user_id)


class PortfolioService:
    def __init__(
        self,
        *,
        account_repository: AccountRepository | None = None,
        portfolio_repository: PortfolioRepository | None = None,
        order_repository: OrderRepository | None = None,
    ) -> None:
        self.account_repository = account_repository or AccountRepository()
        self.portfolio_repository = portfolio_repository or PortfolioRepository()
        self.order_repository = order_repository or OrderRepository()

    def _storage(self, user_id: str, output_dir: str | Path, db_path: str | Path | None) -> PortfolioStorage:
        return PortfolioStorage(db_path, output_dir=portfolio_user_dir(output_dir, user_id))

    def _sources(self, user_id: str, output_dir: str | Path, db_path: str | Path | None) -> list[dict[str, Any]]:
        storage = self._storage(user_id, output_dir, db_path)
        return [
            _source("paper_account_latest", storage.account_latest_path),
            _source("paper_positions_latest", storage.positions_latest_path),
            _source("paper_orders_latest", storage.orders_latest_path),
        ]

    def get_account_summary(
        self,
        user_id: str,
        *,
        output_dir: str | Path = "outputs",
        db_path: str | Path | None = None,
    ) -> dict[str, Any]:
        user = str(user_id or "default")
        account = self.account_repository.load_account(user, output_dir=output_dir, db_path=db_path)
        account_dict = _to_dict(account)
        position_market_value = safe_float(account_dict.get("position_market_value"), 0.0)
        total_assets = safe_float(account_dict.get("total_assets"), safe_float(account_dict.get("cash"), 0.0))
        cash = safe_float(account_dict.get("cash"), 0.0)
        summary = {
            "cash": cash,
            "total_assets": total_assets,
            "position_market_value": position_market_value,
            "cash_ratio": cash / total_assets if total_assets > 0 else 0.0,
            "net_contribution": safe_float(account_dict.get("net_contribution"), 0.0),
            "absolute_profit": safe_float(account_dict.get("absolute_profit"), 0.0),
            "time_weighted_return": safe_float(account_dict.get("time_weighted_return"), 0.0),
            "max_drawdown": safe_float(account_dict.get("max_drawdown"), 0.0),
        }
        return {
            "user_id": user,
            "account": account_dict,
            "account_summary": summary,
            "summary": summary,
            "as_of_date": str(account_dict.get("updated_at") or ""),
            "sources": self._sources(user, output_dir, db_path),
            "not_executed": True,
            "mutation_performed": False,
        }

    def get_current_positions(
        self,
        user_id: str,
        *,
        output_dir: str | Path = "outputs",
        db_path: str | Path | None = None,
    ) -> dict[str, Any]:
        user = str(user_id or "default")
        rows = [_to_dict(item) for item in self.portfolio_repository.load_positions(user, output_dir=output_dir, db_path=db_path)]
        active = _active_positions(rows)
        return {
            "user_id": user,
            "positions": rows,
            "active_positions": active,
            "position_count": len(active),
            "position_market_value": sum(safe_float(row.get("market_value"), 0.0) for row in active),
            "position_weights": self.get_position_weights(user, output_dir=output_dir, db_path=db_path)["position_weights"],
            "sources": self._sources(user, output_dir, db_path),
            "not_executed": True,
            "mutation_performed": False,
        }

    def get_current_orders(
        self,
        user_id: str,
        *,
        output_dir: str | Path = "outputs",
        db_path: str | Path | None = None,
    ) -> dict[str, Any]:
        user = str(user_id or "default")
        rows = [_to_dict(item) for item in self.order_repository.load_orders(user, output_dir=output_dir, db_path=db_path)]
        latest_trade_date = ""
        dates = [str(row.get("trade_date") or "") for row in rows if row.get("trade_date")]
        if dates:
            latest_trade_date = sorted(dates)[-1]
        return {
            "user_id": user,
            "orders": rows,
            "order_count": len(rows),
            "latest_trade_date": latest_trade_date,
            "sources": self._sources(user, output_dir, db_path),
            "not_executed": True,
            "mutation_performed": False,
        }

    def get_cash_state(
        self,
        user_id: str,
        *,
        output_dir: str | Path = "outputs",
        db_path: str | Path | None = None,
    ) -> dict[str, Any]:
        account = self.get_account_summary(user_id, output_dir=output_dir, db_path=db_path)
        summary = dict(account.get("account_summary") or {})
        return {
            "user_id": str(user_id or "default"),
            "cash_state": {
                "cash": summary.get("cash", 0.0),
                "cash_ratio": summary.get("cash_ratio", 0.0),
                "total_assets": summary.get("total_assets", 0.0),
                "position_market_value": summary.get("position_market_value", 0.0),
            },
            "not_executed": True,
            "mutation_performed": False,
        }

    def get_position_weights(
        self,
        user_id: str,
        *,
        output_dir: str | Path = "outputs",
        db_path: str | Path | None = None,
    ) -> dict[str, Any]:
        user = str(user_id or "default")
        positions = [_to_dict(item) for item in self.portfolio_repository.load_positions(user, output_dir=output_dir, db_path=db_path)]
        weights = {
            str(row.get("stock_code") or ""): safe_float(row.get("position_ratio"), 0.0)
            for row in positions
            if safe_float(row.get("quantity"), 0.0) > 0.0 and str(row.get("stock_code") or "")
        }
        return {
            "user_id": user,
            "position_weights": weights,
            "max_single_weight": max(weights.values(), default=0.0),
            "not_executed": True,
            "mutation_performed": False,
        }

    def get_historical_account_snapshot(
        self,
        user_id: str,
        trade_date: str,
        *,
        output_dir: str | Path = "outputs",
        db_path: str | Path | None = None,
    ) -> dict[str, Any]:
        snapshot = self.account_repository.load_historical_account_snapshot(
            str(user_id or "default"),
            trade_date,
            output_dir=output_dir,
            db_path=db_path,
        )
        return {
            "user_id": str(user_id or "default"),
            "trade_date": str(trade_date or ""),
            "account_snapshot": snapshot,
            "not_executed": True,
            "mutation_performed": False,
        }

    def get_portfolio_state(
        self,
        user_id: str,
        *,
        output_dir: str | Path = "outputs",
        db_path: str | Path | None = None,
    ) -> dict[str, Any]:
        user = str(user_id or "default")
        account = self.get_account_summary(user, output_dir=output_dir, db_path=db_path)
        positions = self.get_current_positions(user, output_dir=output_dir, db_path=db_path)
        orders = self.get_current_orders(user, output_dir=output_dir, db_path=db_path)
        cash_state = self.get_cash_state(user, output_dir=output_dir, db_path=db_path)
        summary = {
            "position_count": positions["position_count"],
            "order_count": orders["order_count"],
            "cash": account["account_summary"]["cash"],
            "total_assets": account["account_summary"]["total_assets"],
            "position_market_value": account["account_summary"]["position_market_value"],
            "cash_ratio": account["account_summary"]["cash_ratio"],
        }
        return {
            "user_id": user,
            "account": account["account"],
            "account_summary": account["account_summary"],
            "positions": positions["positions"],
            "active_positions": positions["active_positions"],
            "orders": orders["orders"],
            "position_count": positions["position_count"],
            "order_count": orders["order_count"],
            "cash": summary["cash"],
            "total_assets": summary["total_assets"],
            "cash_state": cash_state["cash_state"],
            "position_weights": positions["position_weights"],
            "summary": summary,
            "as_of_date": account.get("as_of_date") or orders.get("latest_trade_date") or "",
            "sources": self._sources(user, output_dir, db_path),
            "not_executed": True,
            "mutation_performed": False,
        }


portfolio_service = PortfolioService()
