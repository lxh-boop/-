from __future__ import annotations

from pathlib import Path
from typing import Any

from database.schemas import json_dumps, json_loads
from database.sqlite_store import SQLiteStore


class PortfolioRepository:
    def __init__(self, db_path: str | Path | None = None):
        self.store = SQLiteStore(db_path)

    def insert_position(self, record: dict[str, Any]) -> dict[str, Any]:
        return self.store.upsert("portfolio_position", record)

    def get_position(self, position_id: str) -> dict[str, Any] | None:
        return self.store.get("portfolio_position", {"position_id": position_id})

    def list_positions(self, user_id: str | None = None) -> list[dict[str, Any]]:
        filters = {"user_id": user_id} if user_id else None
        return self.store.list("portfolio_position", filters=filters, order_by="updated_at")

    def update_position(self, position_id: str, changes: dict[str, Any]) -> int:
        return self.store.update("portfolio_position", {"position_id": position_id}, changes)

    def insert_paper_account(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = dict(record)
        payload.setdefault("is_paper_trading", 1)
        return self.store.upsert("paper_account", payload)

    def get_paper_account(self, account_id: str) -> dict[str, Any] | None:
        return self.store.get("paper_account", {"account_id": account_id})

    def list_paper_accounts(self, user_id: str | None = None) -> list[dict[str, Any]]:
        filters = {"user_id": user_id} if user_id else None
        return self.store.list("paper_account", filters=filters, order_by="updated_at")

    def update_paper_account(self, account_id: str, changes: dict[str, Any]) -> int:
        return self.store.update("paper_account", {"account_id": account_id}, changes)

    def insert_paper_order(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = dict(record)
        payload.setdefault("is_paper_trading", 1)
        return self.store.upsert("paper_order", payload)

    def get_paper_order(self, order_id: str) -> dict[str, Any] | None:
        return self.store.get("paper_order", {"order_id": order_id})

    def list_paper_orders(
        self,
        user_id: str | None = None,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        filters = {}
        if user_id:
            filters["user_id"] = user_id
        if account_id:
            filters["account_id"] = account_id
        return self.store.list("paper_order", filters=filters or None, order_by="created_at")

    def insert_paper_decision(self, record: dict[str, Any]) -> dict[str, Any]:
        return self.store.upsert("paper_decision_log", dict(record))

    def list_paper_decisions(self, user_id: str | None = None, trade_date: str | None = None) -> list[dict[str, Any]]:
        filters = {}
        if user_id:
            filters["user_id"] = user_id
        if trade_date:
            filters["trade_date"] = trade_date
        return self.store.list("paper_decision_log", filters=filters or None, order_by="decision_time")

    def insert_trading_behavior(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = dict(record)
        if isinstance(payload.get("preferred_industries"), (list, dict)):
            payload["preferred_industries"] = json_dumps(payload["preferred_industries"])
        return self.store.upsert("trading_behavior", payload)

    def insert_cash_flow(self, record: dict[str, Any]) -> dict[str, Any]:
        return self.store.upsert("paper_cash_flow", dict(record))

    def get_cash_flow(self, cash_flow_id: str) -> dict[str, Any] | None:
        return self.store.get("paper_cash_flow", {"cash_flow_id": cash_flow_id})

    def list_cash_flows(self, user_id: str | None = None) -> list[dict[str, Any]]:
        filters = {"user_id": user_id} if user_id else None
        return self.store.list("paper_cash_flow", filters=filters, order_by="effective_date")

    def update_cash_flow(self, cash_flow_id: str, changes: dict[str, Any]) -> int:
        return self.store.update("paper_cash_flow", {"cash_flow_id": cash_flow_id}, changes)

    def insert_nav_record(self, record: dict[str, Any]) -> dict[str, Any]:
        return self.store.upsert("paper_nav_history", dict(record))

    def list_nav_history(self, user_id: str | None = None) -> list[dict[str, Any]]:
        filters = {"user_id": user_id} if user_id else None
        return self.store.list("paper_nav_history", filters=filters, order_by="trade_date")

    def upsert_trading_settings(self, record: dict[str, Any]) -> dict[str, Any]:
        return self.store.upsert("paper_trading_settings", dict(record))

    def get_trading_settings(self, user_id: str, effective_date: str = "") -> dict[str, Any] | None:
        rows = self.store.list(
            "paper_trading_settings",
            filters={"user_id": user_id, "effective_date": effective_date},
            order_by="updated_at",
        )
        if rows:
            return rows[-1]
        rows = self.store.list("paper_trading_settings", filters={"user_id": user_id}, order_by="updated_at")
        return rows[-1] if rows else None

    def insert_account_snapshot(self, record: dict[str, Any]) -> dict[str, Any]:
        return self.store.upsert("paper_account_snapshot", dict(record))

    def insert_replay_run(self, record: dict[str, Any]) -> dict[str, Any]:
        return self.store.upsert("paper_replay_run", dict(record))

    def insert_daily_replay_audit(self, record: dict[str, Any]) -> dict[str, Any]:
        return self.store.upsert("paper_daily_replay_audit", dict(record))

    def insert_stock_decision_audit(self, record: dict[str, Any]) -> dict[str, Any]:
        return self.store.upsert("paper_stock_decision_audit", dict(record))

    def insert_order_reason_audit(self, record: dict[str, Any]) -> dict[str, Any]:
        return self.store.upsert("paper_order_reason_audit", dict(record))

    def get_trading_behavior(self, behavior_id: str) -> dict[str, Any] | None:
        row = self.store.get("trading_behavior", {"behavior_id": behavior_id})
        if row:
            row["preferred_industries"] = json_loads(row.get("preferred_industries"), default=[])
        return row
