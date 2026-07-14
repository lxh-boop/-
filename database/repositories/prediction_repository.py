from __future__ import annotations

from pathlib import Path
from typing import Any

from database.sqlite_store import SQLiteStore


class PredictionRepository:
    def __init__(self, db_path: str | Path | None = None):
        self.store = SQLiteStore(db_path)

    def insert_prediction(self, record: dict[str, Any]) -> dict[str, Any]:
        return self.store.upsert("model_prediction", record)

    def get_prediction(self, prediction_id: str) -> dict[str, Any] | None:
        return self.store.get("model_prediction", {"prediction_id": prediction_id})

    def list_predictions(
        self,
        trade_date: str | None = None,
        stock_code: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        filters = {}
        if trade_date:
            filters["trade_date"] = trade_date
        if stock_code:
            filters["stock_code"] = stock_code
        return self.store.list(
            "model_prediction",
            filters=filters or None,
            order_by="trade_date",
            limit=limit,
        )

    def update_prediction(self, prediction_id: str, changes: dict[str, Any]) -> int:
        return self.store.update("model_prediction", {"prediction_id": prediction_id}, changes)
