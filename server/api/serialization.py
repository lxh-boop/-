from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

TYPE_KEY = "__transport_type__"


def _clean_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if value is pd.NaT:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


def encode_transport(value: Any) -> Any:
    value = _clean_scalar(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, pd.DataFrame):
        clean = value.copy()
        clean = clean.where(pd.notna(clean), None)
        records = [
            {str(key): encode_transport(item) for key, item in row.items()}
            for row in clean.to_dict(orient="records")
        ]
        return {
            TYPE_KEY: "dataframe",
            "columns": [str(column) for column in clean.columns],
            "records": records,
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
    if isinstance(value, Enum):
        return {TYPE_KEY: "enum", "value": encode_transport(value.value)}
    if isinstance(value, tuple):
        return {TYPE_KEY: "tuple", "items": [encode_transport(item) for item in value]}
    if isinstance(value, set):
        return {TYPE_KEY: "set", "items": [encode_transport(item) for item in value]}
    if isinstance(value, list):
        return [encode_transport(item) for item in value]
    if isinstance(value, dict):
        return {str(key): encode_transport(item) for key, item in value.items()}
    if is_dataclass(value):
        payload = asdict(value)
        for property_name in ("ok", "success", "message", "data", "status"):
            if property_name not in payload and hasattr(value, property_name):
                try:
                    payload[property_name] = getattr(value, property_name)
                except Exception:
                    pass
        return {
            TYPE_KEY: "object",
            "class_name": type(value).__name__,
            "data": encode_transport(payload),
        }
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            payload = value.to_dict()
            return {
                TYPE_KEY: "object",
                "class_name": type(value).__name__,
                "data": encode_transport(payload),
            }
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        payload = {
            key: item
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
        for property_name in ("ok", "success", "message", "data", "status"):
            if property_name not in payload and hasattr(value, property_name):
                try:
                    payload[property_name] = getattr(value, property_name)
                except Exception:
                    pass
        return {
            TYPE_KEY: "object",
            "class_name": type(value).__name__,
            "data": encode_transport(payload),
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
    if value_type == "enum":
        return decode_transport(value.get("value"))
    if value_type == "tuple":
        return tuple(decode_transport(item) for item in value.get("items") or [])
    if value_type == "set":
        return set(decode_transport(item) for item in value.get("items") or [])
    if value_type == "object":
        return decode_transport(value.get("data") or {})
    return {str(key): decode_transport(item) for key, item in value.items()}
