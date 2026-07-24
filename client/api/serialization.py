from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

TYPE_KEY = "__transport_type__"


class RemoteObject:
    def __init__(self, class_name: str, data: dict[str, Any] | None = None) -> None:
        self._class_name = str(class_name or "RemoteObject")
        for key, value in dict(data or {}).items():
            setattr(self, str(key), value)

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in vars(self).items()
            if not str(key).startswith("_")
        }

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __repr__(self) -> str:
        return f"{self._class_name}({self.to_dict()!r})"


def encode_transport(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, np.ndarray):
        return [encode_transport(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return encode_transport(value.item())
    if isinstance(value, pd.DataFrame):
        clean = value.where(pd.notna(value), None)
        return {
            TYPE_KEY: "dataframe",
            "columns": [str(column) for column in clean.columns],
            "records": [
                {str(key): encode_transport(item) for key, item in row.items()}
                for row in clean.to_dict(orient="records")
            ],
        }
    if isinstance(value, pd.Series):
        return {
            TYPE_KEY: "series",
            "name": str(value.name or ""),
            "data": {str(key): encode_transport(item) for key, item in value.to_dict().items()},
        }
    if isinstance(value, Path):
        return {TYPE_KEY: "path", "value": str(value)}
    if isinstance(value, datetime):
        return {TYPE_KEY: "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {TYPE_KEY: "date", "value": value.isoformat()}
    if isinstance(value, time):
        return {TYPE_KEY: "time", "value": value.isoformat()}
    if isinstance(value, tuple):
        return {TYPE_KEY: "tuple", "items": [encode_transport(item) for item in value]}
    if isinstance(value, set):
        return {TYPE_KEY: "set", "items": [encode_transport(item) for item in value]}
    if isinstance(value, list):
        return [encode_transport(item) for item in value]
    if isinstance(value, dict):
        return {str(key): encode_transport(item) for key, item in value.items()}
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return {
            TYPE_KEY: "object",
            "class_name": type(value).__name__,
            "data": encode_transport(value.to_dict()),
        }
    if hasattr(value, "__dict__"):
        return {
            TYPE_KEY: "object",
            "class_name": type(value).__name__,
            "data": encode_transport({k: v for k, v in vars(value).items() if not k.startswith("_")}),
        }
    return str(value)


def decode_transport(value: Any) -> Any:
    if isinstance(value, list):
        return [decode_transport(item) for item in value]
    if not isinstance(value, dict):
        return value
    value_type = value.get(TYPE_KEY)
    if value_type == "dataframe":
        records = decode_transport(value.get("records") or [])
        columns = list(value.get("columns") or [])
        return pd.DataFrame(records, columns=columns or None)
    if value_type == "series":
        return pd.Series(decode_transport(value.get("data") or {}), name=value.get("name") or None)
    if value_type == "path":
        return Path(str(value.get("value") or ""))
    if value_type == "datetime":
        return datetime.fromisoformat(str(value.get("value") or ""))
    if value_type == "date":
        return date.fromisoformat(str(value.get("value") or ""))
    if value_type == "time":
        return time.fromisoformat(str(value.get("value") or ""))
    if value_type == "tuple":
        return tuple(decode_transport(item) for item in value.get("items") or [])
    if value_type == "set":
        return set(decode_transport(item) for item in value.get("items") or [])
    if value_type == "object":
        data = decode_transport(value.get("data") or {})
        return RemoteObject(str(value.get("class_name") or "RemoteObject"), data if isinstance(data, dict) else {"value": data})
    return {str(key): decode_transport(item) for key, item in value.items()}
