from __future__ import annotations

import csv
import json
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from database.repositories import PortfolioRepository
from portfolio.cash_flow import cash_flow_from_dict, list_cash_flows, save_cash_flow, write_cash_flow_history
from portfolio.paper_account import account_from_dict
from portfolio.paper_order import create_paper_order
from portfolio.paper_position import create_position
from portfolio.schemas import PaperAccount, PaperCashFlow, PaperNavRecord, PaperOrder, PaperPosition, PaperTradingSettings, PortfolioRiskReport
from portfolio.trading_cost_config import TradingCostConfig, cost_config_from_dict, default_trading_cost_config


DEFAULT_OUTPUT_DIR = Path("outputs") / "portfolio"
POSITION_SNAPSHOT_FIELDNAMES = [
    "user_id",
    "trade_date",
    "stock_code",
    "stock_name",
    "quantity",
    "available_quantity",
    "average_cost",
    "last_price",
    "market_value",
    "position_weight",
    "unrealized_profit",
    "realized_profit",
    "source_trade_date",
    "updated_at",
    "run_id",
    "position_id",
    "cost_price",
    "current_price",
    "position_ratio",
    "industry",
    "unrealized_pnl",
]


class PortfolioStorage:
    """Database-first storage with local paper-trading fallback files."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        output_dir: str | Path = DEFAULT_OUTPUT_DIR,
        use_database: bool = True,
    ):
        self.db_path = db_path
        self.output_dir = Path(output_dir)
        self.use_database = use_database
        self._repo: PortfolioRepository | None = None

    @property
    def repo(self) -> PortfolioRepository:
        if self._repo is None:
            self._repo = PortfolioRepository(self.db_path)
        return self._repo

    @property
    def account_path(self) -> Path:
        return self.output_dir / "paper_account.json"

    @property
    def positions_path(self) -> Path:
        return self.output_dir / "paper_positions.csv"

    @property
    def orders_path(self) -> Path:
        return self.output_dir / "paper_orders.csv"

    @property
    def risk_report_path(self) -> Path:
        return self.output_dir / "portfolio_risk_report.json"

    @property
    def account_latest_path(self) -> Path:
        return self.output_dir / "paper_account_latest.json"

    @property
    def positions_latest_path(self) -> Path:
        return self.output_dir / "paper_positions_latest.csv"

    @property
    def orders_latest_path(self) -> Path:
        return self.output_dir / "paper_orders_latest.csv"

    @property
    def risk_report_latest_path(self) -> Path:
        return self.output_dir / "portfolio_risk_report_latest.json"

    @property
    def decisions_latest_path(self) -> Path:
        return self.output_dir / "ai_paper_decisions_latest.json"

    @property
    def cash_flows_path(self) -> Path:
        return self.output_dir / "paper_cash_flows.csv"

    @property
    def nav_latest_path(self) -> Path:
        return self.output_dir / "paper_nav_latest.csv"

    @property
    def trading_settings_path(self) -> Path:
        return self.output_dir / "paper_trading_settings.json"

    def _ensure_output_dir(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _history_path(self, category: str, prefix: str, trade_date: str, suffix: str) -> Path:
        token = self._latest_date_token(trade_date)
        clean_suffix = str(suffix or datetime.now().strftime("%H%M%S")).replace(":", "").replace(" ", "_").replace("-", "")
        return self.output_dir / "history" / category / f"{prefix}_{token}_{clean_suffix}"

    def _latest_date_token(self, trade_date: str | None = None) -> str:
        token = str(trade_date or datetime.now().strftime("%Y-%m-%d")).replace("-", "")[:8]
        return token if len(token) == 8 and token.isdigit() else datetime.now().strftime("%Y%m%d")

    def _try_database(self, action):
        if not self.use_database:
            raise RuntimeError("database disabled for portfolio storage")
        return action()

    def save_account(self, account: PaperAccount) -> dict[str, Any]:
        try:
            record = self._try_database(lambda: self.repo.insert_paper_account(account.to_dict()))
            self._ensure_output_dir()
            self.account_path.write_text(
                json.dumps(account.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.account_latest_path.write_text(
                json.dumps(account.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return record
        except Exception:
            self._ensure_output_dir()
            self.account_path.write_text(
                json.dumps(account.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.account_latest_path.write_text(
                json.dumps(account.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return account.to_dict()

    def load_account(self, account_id: str | None = None) -> PaperAccount | None:
        for path in [self.account_latest_path, self.account_path]:
            if path.exists():
                return account_from_dict(json.loads(path.read_text(encoding="utf-8")))
        if account_id:
            try:
                row = self._try_database(lambda: self.repo.get_paper_account(account_id))
                if row:
                    return account_from_dict(row)
            except Exception:
                pass
        return None

    def save_positions(self, positions: list[PaperPosition]) -> list[dict[str, Any]]:
        records = [position.to_dict() for position in positions]
        try:
            saved = self._try_database(
                lambda: [self.repo.insert_position(position.to_database_record()) for position in positions]
            )
            self._ensure_output_dir()
            self._write_csv(self.positions_path, records)
            self._write_csv(self.positions_latest_path, records)
            return saved
        except Exception:
            self._ensure_output_dir()
            self._write_csv(self.positions_path, records)
            self._write_csv(self.positions_latest_path, records)
            return records

    def load_positions(self, user_id: str | None = None) -> list[PaperPosition]:
        local_path = self.positions_latest_path if self.positions_latest_path.exists() else self.positions_path
        if local_path.exists():
            with local_path.open("r", encoding="utf-8-sig", newline="") as file:
                rows = list(csv.DictReader(file))
            if user_id:
                rows = [row for row in rows if row.get("user_id") == user_id]
            return [self._position_from_record(row) for row in rows]
        try:
            rows = self._try_database(lambda: self.repo.list_positions(user_id))
            if rows:
                return [self._position_from_record(row) for row in rows]
        except Exception:
            pass
        return []

    def _position_snapshot_records(
        self,
        positions: list[PaperPosition],
        trade_date: str,
        run_id: str = "",
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for position in positions or []:
            quantity = float(position.quantity or 0.0)
            if quantity <= 0:
                continue
            last_price = float(position.current_price or 0.0)
            average_cost = float(position.cost_price or 0.0)
            record = {
                "user_id": position.user_id,
                "trade_date": trade_date,
                "stock_code": str(position.stock_code or "").split(".")[0].zfill(6),
                "stock_name": position.stock_name,
                "quantity": quantity,
                "available_quantity": quantity,
                "average_cost": average_cost,
                "last_price": last_price,
                "market_value": float(position.market_value or 0.0),
                "position_weight": float(position.position_ratio or 0.0),
                "unrealized_profit": float(position.unrealized_pnl or 0.0),
                "realized_profit": 0.0,
                "source_trade_date": trade_date,
                "updated_at": position.updated_at,
                "run_id": run_id,
                "position_id": position.position_id,
                "cost_price": average_cost,
                "current_price": last_price,
                "position_ratio": float(position.position_ratio or 0.0),
                "industry": position.industry,
                "unrealized_pnl": float(position.unrealized_pnl or 0.0),
            }
            records.append(record)
        return records

    def load_position_snapshot(self, trade_date: str, user_id: str | None = None, fallback: bool = True) -> list[PaperPosition]:
        token = self._latest_date_token(trade_date)
        root = self.output_dir / "history" / "positions"
        candidates: list[Path] = []
        exact = root / f"positions_{token}.csv"
        if exact.exists():
            candidates.append(exact)
        elif fallback and root.exists():
            for path in root.glob("positions_*.csv"):
                path_token = path.stem.replace("positions_", "")[:8]
                if len(path_token) == 8 and path_token.isdigit() and path_token <= token:
                    candidates.append(path)
        if not candidates:
            return []
        path = sorted(candidates, key=lambda item: item.stem.replace("positions_", "")[:8])[-1]
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
        if user_id:
            rows = [row for row in rows if row.get("user_id") == user_id]
        return [self._position_from_record(row) for row in rows]

    def save_order(self, order: PaperOrder) -> dict[str, Any]:
        saved = self.save_orders([order])
        return saved[0] if saved else {}

    def save_cash_flow(self, flow: PaperCashFlow) -> PaperCashFlow:
        root_output = self.output_dir.parent.parent if self.output_dir.name else Path("outputs")
        return save_cash_flow(
            flow,
            db_path=self.db_path,
            output_dir=root_output,
            use_database=self.use_database,
        )

    def load_cash_flows(self, user_id: str | None = None) -> list[PaperCashFlow]:
        user = user_id or self.output_dir.name
        root_output = self.output_dir.parent.parent if self.output_dir.name else Path("outputs")
        return list_cash_flows(
            user,
            db_path=self.db_path,
            output_dir=root_output,
            use_database=self.use_database,
        )

    def save_trading_settings(self, settings: TradingCostConfig | PaperTradingSettings | dict[str, Any]) -> dict[str, Any]:
        if isinstance(settings, TradingCostConfig):
            record = settings.to_dict()
        elif hasattr(settings, "to_dict"):
            record = settings.to_dict()
        else:
            record = dict(settings)
        record.setdefault("settings_id", f"paper_trading_settings_{record.get('user_id') or self.output_dir.name}_default")
        try:
            saved = self._try_database(lambda: self.repo.upsert_trading_settings(record))
        except Exception:
            saved = record
        self._ensure_output_dir()
        self.trading_settings_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return saved

    def load_trading_settings(self, user_id: str | None = None) -> TradingCostConfig:
        user = user_id or self.output_dir.name or "default"
        if self.trading_settings_path.exists():
            try:
                return cost_config_from_dict(json.loads(self.trading_settings_path.read_text(encoding="utf-8")), user)
            except Exception:
                pass
        try:
            row = self._try_database(lambda: self.repo.get_trading_settings(user))
            if row:
                return cost_config_from_dict(row, user)
        except Exception:
            pass
        return default_trading_cost_config(user)

    def save_nav_record(self, record: dict[str, Any] | PaperNavRecord) -> dict[str, Any]:
        payload = record.to_dict() if hasattr(record, "to_dict") else dict(record)
        payload.setdefault("composite_nav", payload.get("nav", 1.0))
        payload.setdefault("nav", payload.get("composite_nav", 1.0))
        try:
            self._try_database(lambda: self.repo.insert_nav_record(payload))
        except Exception:
            pass
        self._ensure_output_dir()
        existing = []
        if self.nav_latest_path.exists():
            with self.nav_latest_path.open("r", encoding="utf-8-sig", newline="") as file:
                existing = list(csv.DictReader(file))
        by_date = {row.get("trade_date"): row for row in existing if row.get("trade_date")}
        by_date[str(payload.get("trade_date") or "")] = {key: str(value) for key, value in payload.items()}
        rows = sorted(by_date.values(), key=lambda row: str(row.get("trade_date") or ""))
        self._write_csv(self.nav_latest_path, rows)
        dated_nav = self.output_dir / "history" / "nav" / f"nav_{self._latest_date_token(str(payload.get('trade_date') or ''))}.csv"
        self._write_csv(dated_nav, [payload])
        return payload

    def load_nav_history(self, user_id: str | None = None) -> list[dict[str, Any]]:
        if self.nav_latest_path.exists():
            with self.nav_latest_path.open("r", encoding="utf-8-sig", newline="") as file:
                rows = list(csv.DictReader(file))
            if user_id:
                rows = [row for row in rows if row.get("user_id") == user_id]
            for row in rows:
                row.setdefault("composite_nav", row.get("nav", "1.0"))
            return rows
        try:
            rows = self._try_database(lambda: self.repo.list_nav_history(user_id))
            for row in rows:
                row.setdefault("composite_nav", row.get("nav", 1.0))
            return rows
        except Exception:
            return []

    def save_orders(self, orders: list[PaperOrder]) -> list[dict[str, Any]]:
        records = [
            order.to_dict()
            for order in orders
            if str(order.action) in {"buy", "sell"}
            and str(order.paper_action) in {"paper_buy", "paper_sell", "paper_reduce"}
            and float(order.quantity or 0.0) > 0
            and float(order.executed_price or 0.0) > 0
        ]
        try:
            saved = self._try_database(lambda: [self.repo.insert_paper_order(record) for record in records])
            self._ensure_output_dir()
            existing = []
            if self.orders_path.exists():
                with self.orders_path.open("r", encoding="utf-8-sig", newline="") as file:
                    existing = list(csv.DictReader(file))
            by_id = {row.get("order_id"): row for row in existing if row.get("order_id")}
            for record in records:
                by_id[record["order_id"]] = {key: str(value) for key, value in record.items()}
            self._write_csv(self.orders_path, list(by_id.values()))
            self._write_csv(self.orders_latest_path, records)
            return saved
        except Exception:
            self._ensure_output_dir()
            existing = []
            if self.orders_path.exists():
                with self.orders_path.open("r", encoding="utf-8-sig", newline="") as file:
                    existing = list(csv.DictReader(file))
            by_id = {row.get("order_id"): row for row in existing if row.get("order_id")}
            for record in records:
                by_id[record["order_id"]] = {key: str(value) for key, value in record.items()}
            self._write_csv(self.orders_path, list(by_id.values()))
            self._write_csv(self.orders_latest_path, records)
            return records

    def load_orders(self, user_id: str | None = None, account_id: str | None = None) -> list[PaperOrder]:
        local_path = self.orders_latest_path if self.orders_latest_path.exists() else self.orders_path
        if local_path.exists():
            with local_path.open("r", encoding="utf-8-sig", newline="") as file:
                rows = list(csv.DictReader(file))
            if user_id:
                rows = [row for row in rows if row.get("user_id") == user_id]
            if account_id:
                rows = [row for row in rows if row.get("account_id") == account_id]
            return [self._order_from_record(row) for row in rows]
        try:
            rows = self._try_database(lambda: self.repo.list_paper_orders(user_id=user_id, account_id=account_id))
            if rows:
                return [self._order_from_record(row) for row in rows]
        except Exception:
            pass
        return []

    def save_risk_report(self, report: PortfolioRiskReport) -> Path:
        self._ensure_output_dir()
        self.risk_report_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.risk_report_latest_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.risk_report_path

    def save_ai_paper_decisions(
        self,
        decisions: list[dict[str, Any]],
        trade_date: str,
        decision_time: str,
    ) -> dict[str, Path]:
        self._ensure_output_dir()
        for record in decisions:
            try:
                self._try_database(lambda record=record: self.repo.insert_paper_decision(record))
            except Exception:
                pass
        payload = json.dumps(decisions, ensure_ascii=False, indent=2)
        self.decisions_latest_path.write_text(payload, encoding="utf-8")
        dated = self.output_dir / "history" / "decisions" / f"ai_paper_decisions_{self._latest_date_token(trade_date)}.json"
        run_path = self._history_path("decisions", "ai_paper_decisions", trade_date, f"{decision_time}.json")
        dated.parent.mkdir(parents=True, exist_ok=True)
        run_path.parent.mkdir(parents=True, exist_ok=True)
        dated.write_text(payload, encoding="utf-8")
        run_path.write_text(payload, encoding="utf-8")
        return {"latest": self.decisions_latest_path, "dated": dated, "run": run_path}

    def write_daily_snapshot(
        self,
        account: PaperAccount | None = None,
        positions: list[PaperPosition] | None = None,
        orders: list[PaperOrder] | None = None,
        risk_report: PortfolioRiskReport | dict[str, Any] | None = None,
        decisions: list[dict[str, Any]] | None = None,
        trade_date: str | None = None,
        decision_time: str | None = None,
        strategy_metadata: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        self._ensure_output_dir()
        decision_time = decision_time or datetime.now().strftime("%Y%m%d_%H%M%S")
        trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")
        paths: dict[str, str] = {}
        strategy_metadata = dict(strategy_metadata or {})
        real_order_records = [
            order.to_dict()
            for order in (orders or [])
            if str(order.action) in {"buy", "sell"}
            and str(order.paper_action) in {"paper_buy", "paper_sell", "paper_reduce"}
            and float(order.quantity or 0.0) > 0
            and float(order.executed_price or 0.0) > 0
        ]
        active_positions = [position for position in (positions or []) if float(position.quantity or 0.0) > 0]
        position_records = self._position_snapshot_records(active_positions, trade_date, run_id=str(decision_time or ""))
        for record in position_records:
            record.update(
                {
                    "strategy_id": str(
                        strategy_metadata.get("strategy_id") or ""
                    ),
                    "strategy_version": str(
                        strategy_metadata.get("strategy_version") or ""
                    ),
                    "binding_id": str(
                        strategy_metadata.get("binding_id") or ""
                    ),
                    "config_hash": str(
                        strategy_metadata.get("config_hash") or ""
                    ),
                    "resolved_config": json.dumps(
                        strategy_metadata.get("resolved_config") or {},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                }
            )
        position_market_value = sum(float(position.market_value or 0.0) for position in active_positions)
        price_missing_count = sum(
            1
            for position in active_positions
            if float(position.quantity or 0.0) > 0 and float(position.current_price or 0.0) <= 0
        )
        if account is not None:
            account_record = account.to_dict()
            recalculated_total = float(account.cash or 0.0) + position_market_value
            account_record["position_market_value"] = position_market_value
            account_record["total_assets"] = recalculated_total
            asset_difference = float(account.total_assets or recalculated_total) - recalculated_total
            if price_missing_count > 0:
                status = "missing_price"
                error = "missing valid mark price"
            elif abs(asset_difference) > 0.01:
                status = "failed"
                error = "total_assets does not equal cash plus position market value"
            else:
                status = "passed"
                error = ""
            if status != "passed":
                raise ValueError(f"account reconciliation failed for {trade_date}: {error}")
            account_record.update(
                {
                    "reconciliation_status": status,
                    "reconciliation_error": error,
                    "position_snapshot_count": len(position_records),
                    "order_count": len(real_order_records),
                    "price_missing_count": price_missing_count,
                    **strategy_metadata,
                }
            )
            snapshot_record = {
                "snapshot_id": (
                    f"paper_account_snapshot_{account.user_id}_"
                    f"{self._latest_date_token(trade_date)}_{decision_time}"
                ),
                "user_id": account.user_id,
                "account_id": account.account_id,
                "trade_date": trade_date,
                "cash": float(account.cash or 0.0),
                "position_market_value": position_market_value,
                "total_assets": recalculated_total,
                "net_contribution": float(
                    account.net_contribution or 0.0
                ),
                "daily_return": float(account.daily_return or 0.0),
                "cumulative_return": float(
                    account.cumulative_return or 0.0
                ),
                "time_weighted_return": float(
                    account.time_weighted_return or 0.0
                ),
                "nav": float(account.nav or 1.0),
                "drawdown": float(account.drawdown or 0.0),
                "strategy_id": str(
                    strategy_metadata.get("strategy_id") or ""
                ),
                "strategy_version": str(
                    strategy_metadata.get("strategy_version") or ""
                ),
                "binding_id": str(
                    strategy_metadata.get("binding_id") or ""
                ),
                "config_hash": str(
                    strategy_metadata.get("config_hash") or ""
                ),
                "resolved_config": dict(
                    strategy_metadata.get("resolved_config") or {}
                ),
            }
            try:
                self._try_database(
                    lambda: self.repo.insert_account_snapshot(
                        snapshot_record
                    )
                )
            except Exception:
                pass
            account_payload = json.dumps(account_record, ensure_ascii=False, indent=2)
            dated_account = self.output_dir / "history" / "accounts" / f"account_{self._latest_date_token(trade_date)}.json"
            account_path = self._history_path("accounts", "account", trade_date, f"{decision_time}.json")
            dated_account.parent.mkdir(parents=True, exist_ok=True)
            account_path.parent.mkdir(parents=True, exist_ok=True)
            dated_account.write_text(account_payload, encoding="utf-8")
            account_path.write_text(account_payload, encoding="utf-8")
            paths["account_history"] = str(account_path)
            paths["account_history_dated"] = str(dated_account)
        if positions is not None:
            dated_positions = self.output_dir / "history" / "positions" / f"positions_{self._latest_date_token(trade_date)}.csv"
            run_positions = self._history_path("positions", "positions", trade_date, f"{decision_time}.csv")
            self._write_csv(dated_positions, position_records)
            self._write_csv(run_positions, position_records)
            paths["positions_history"] = str(run_positions)
        if orders is not None:
            dated_orders = self.output_dir / "history" / "orders" / f"orders_{self._latest_date_token(trade_date)}.csv"
            run_orders = self._history_path("orders", "orders", trade_date, f"{decision_time}.csv")
            self._write_csv(dated_orders, real_order_records)
            self._write_csv(run_orders, real_order_records)
            paths["orders_history"] = str(run_orders)
        cash_flows = None
        try:
            cash_flows = self.load_cash_flows(account.user_id if account else "")
        except Exception:
            cash_flows = None
        if cash_flows is not None:
            root_output = self.output_dir.parent.parent if self.output_dir.name else Path("outputs")
            cash_path = write_cash_flow_history(
                account.user_id if account else self.output_dir.name,
                trade_date,
                cash_flows,
                output_dir=root_output,
            )
            paths["cash_flows_history"] = str(cash_path)
        if decisions is not None:
            hold_records = [
                record
                for record in decisions
                if str(record.get("paper_action") or "") in {"paper_hold", "paper_hold", "paper_risk_alert"}
                or float(record.get("order_quantity") or 0.0) <= 0
            ]
            dated_watchlist = self.output_dir / "history" / "hold" / f"watchlist_{self._latest_date_token(trade_date)}.csv"
            run_watchlist = self._history_path("hold", "hold", trade_date, f"{decision_time}.csv")
            self._write_csv(dated_watchlist, hold_records)
            self._write_csv(run_watchlist, hold_records)
            paths["hold_history"] = str(run_watchlist)
        if risk_report is not None:
            risk_payload = risk_report.to_dict() if hasattr(risk_report, "to_dict") else dict(risk_report)
            dated_risk = self.output_dir / "history" / "risk" / f"risk_{self._latest_date_token(trade_date)}.json"
            run_risk = self._history_path("risk", "risk", trade_date, f"{decision_time}.json")
            dated_risk.parent.mkdir(parents=True, exist_ok=True)
            run_risk.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps(risk_payload, ensure_ascii=False, indent=2)
            dated_risk.write_text(text, encoding="utf-8")
            run_risk.write_text(text, encoding="utf-8")
            paths["risk_history"] = str(run_risk)
        if decisions is not None:
            decision_paths = self.save_ai_paper_decisions(decisions, trade_date, decision_time)
            paths.update({f"decisions_{key}": str(value) for key, value in decision_paths.items()})
        return paths

    def save_strategy_execution_history(
        self,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        payload = dict(record)
        identity = "_".join(
            [
                str(payload.get("user_id") or ""),
                str(payload.get("account_id") or ""),
                self._latest_date_token(
                    str(payload.get("trade_date") or "")
                ),
                str(payload.get("run_id") or ""),
            ]
        )
        payload.setdefault(
            "execution_history_id",
            f"strategy_execution_{identity}",
        )
        try:
            return self._try_database(
                lambda: self.repo.insert_strategy_execution_history(
                    payload
                )
            )
        except Exception:
            history_path = self._history_path(
                "strategy",
                "strategy_execution",
                str(payload.get("trade_date") or ""),
                f"{payload.get('run_id') or 'run'}.json",
            )
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return payload

    def list_strategy_execution_history(
        self,
        user_id: str,
        account_id: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            return self._try_database(
                lambda: self.repo.list_strategy_execution_history(
                    user_id,
                    account_id,
                )
            )
        except Exception:
            root = self.output_dir / "history" / "strategy"
            rows: list[dict[str, Any]] = []
            for path in sorted(root.glob("strategy_execution_*.json")):
                try:
                    row = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if str(row.get("user_id") or "") != str(user_id):
                    continue
                if account_id and str(row.get("account_id") or "") != str(
                    account_id
                ):
                    continue
                rows.append(row)
            return rows

    def load_risk_report(self) -> dict[str, Any] | None:
        if not self.risk_report_path.exists():
            return None
        return json.loads(self.risk_report_path.read_text(encoding="utf-8"))

    def _write_csv(self, path: Path, records: list[dict[str, Any]]) -> None:
        self._ensure_output_dir()
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = sorted({key for record in records for key in record})
        if not fieldnames:
            name = path.name
            if "position" in name:
                if "history" in path.parts and name.startswith("positions_"):
                    fieldnames = POSITION_SNAPSHOT_FIELDNAMES
                else:
                    fieldnames = [field.name for field in fields(PaperPosition)]
            elif "order" in name:
                fieldnames = [
                    field.name
                    for field in fields(PaperOrder)
                    if field.name not in {"final_score", "final_action"}
                ]
            elif "hold" in name:
                fieldnames = [
                    "decision_id",
                    "user_id",
                    "trade_date",
                    "decision_time",
                    "stock_code",
                    "stock_name",
                    "paper_action",
                    "target_weight",
                    "current_weight",
                    "order_amount",
                    "order_quantity",
                    "news_adjustment",
                    "user_adjustment",
                    "effective_news_adjustment",
                    "combined_adjustment",
                    "position_adjustment_ratio",
                    "reason",
                    "risk_warning",
                    "triggered_rules",
                    "source_decision_id",
                    "created_at",
                ]
            elif "nav" in name:
                fieldnames = [field.name for field in fields(PaperNavRecord)]
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)

    def _position_from_record(self, row: dict[str, Any]) -> PaperPosition:
        market_value = float(row.get("market_value") or 0.0)
        ratio = float(row.get("position_ratio") or row.get("position_weight") or 0.0)
        total_assets = market_value / ratio if ratio > 0 else 0.0
        return create_position(
            user_id=str(row.get("user_id") or "default_user"),
            stock_code=str(row.get("stock_code") or row.get("asset_code") or ""),
            stock_name=str(row.get("stock_name") or row.get("asset_name") or ""),
            quantity=float(row.get("quantity") or 0.0),
            cost_price=float(row.get("cost_price") or row.get("average_cost") or 0.0),
            current_price=float(row.get("current_price") or row.get("last_price") or row.get("close_price") or 0.0),
            total_assets=total_assets,
            industry=str(row.get("industry") or ""),
            position_id=str(row.get("position_id") or ""),
            updated_at=str(row.get("updated_at") or ""),
        )

    def _order_from_record(self, row: dict[str, Any]) -> PaperOrder:
        return create_paper_order(
            order_id=str(row.get("order_id") or ""),
            user_id=str(row.get("user_id") or "default_user"),
            account_id=str(row.get("account_id") or ""),
            trade_date=str(row.get("trade_date") or ""),
            stock_code=str(row.get("stock_code") or ""),
            stock_name=str(row.get("stock_name") or ""),
            action=str(row.get("action") or "hold"),
            target_weight=float(row.get("target_weight") or 0.0),
            executed_price=float(row.get("executed_price") or 0.0),
            quantity=float(row.get("quantity") or 0.0),
            reason=str(row.get("reason") or ""),
            decision_id=str(row.get("decision_id") or ""),
            decision_time=str(row.get("decision_time") or ""),
            paper_action=str(row.get("paper_action") or ""),
            current_weight=float(row.get("current_weight") or 0.0),
            order_amount=float(row.get("order_amount") or 0.0),
            gross_amount=float(row.get("gross_amount") or row.get("order_amount") or 0.0),
            commission_fee=float(row.get("commission_fee") or 0.0),
            other_fee=float(row.get("other_fee") or 0.0),
            slippage_cost=float(row.get("slippage_cost") or 0.0),
            total_fee=float(row.get("total_fee") or 0.0),
            net_cash_change=float(row.get("net_cash_change") or 0.0),
            applied_buy_cost_rate=float(row.get("applied_buy_cost_rate") or 0.0),
            applied_sell_cost_rate=float(row.get("applied_sell_cost_rate") or 0.0),
            risk_warning=str(row.get("risk_warning") or ""),
            triggered_rules=str(row.get("triggered_rules") or ""),
            job_id=str(row.get("job_id") or ""),
            run_id=str(row.get("run_id") or ""),
            execution_source=str(row.get("execution_source") or ""),
            strategy_id=str(row.get("strategy_id") or ""),
            strategy_version=str(
                row.get("strategy_version") or ""
            ),
            binding_id=str(row.get("binding_id") or ""),
            config_hash=str(row.get("config_hash") or ""),
            resolved_config=(
                row.get("resolved_config")
                if isinstance(row.get("resolved_config"), dict)
                else json.loads(
                    str(row.get("resolved_config") or "{}")
                    .replace("'", '"')
                )
            ),
        )
