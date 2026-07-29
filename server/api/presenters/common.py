from __future__ import annotations

import math
import re
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

_DRIVE_PATH = re.compile(r"(?i)\b[a-z]:[\\/][^\s\"']+")
_PATH_KEYS = {"path", "file_path", "db_path", "database_path", "output_dir", "root", "cwd"}
_SECRET_MARKERS = ("api_key", "token", "password", "secret", "credential", "confirmation_token")
_SAFE_STATUS_CONTAINER_KEYS = {
    "credentials",
    "credential_status",
    "connection_status",
    "configuration_status",
}


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def _is_path_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in _PATH_KEYS or lowered.endswith("_path") or lowered.endswith("_dir")


def _is_safe_status_container(key: str) -> bool:
    return key.lower() in _SAFE_STATUS_CONTAINER_KEYS


def _safe_status_container(value: Any) -> dict[str, bool]:
    """Keep only boolean ``*_configured`` indicators from a sensitive container.

    The browser may display whether a credential-backed capability is configured,
    but it must never receive the credential value itself.  A parent key such as
    ``credentials`` is therefore handled as a restricted status container instead
    of being removed wholesale.
    """

    if not isinstance(value, dict):
        return {}
    output: dict[str, bool] = {}
    for raw_key, item in value.items():
        item_key = str(raw_key)
        if item_key.lower().endswith("_configured"):
            output[item_key] = bool(item)
    return output


def to_browser_value(value: Any, *, key: str = "") -> Any:
    if key and _is_safe_status_container(key):
        return _safe_status_container(value)
    if key and _is_sensitive_key(key):
        if key.lower().endswith("_configured"):
            return bool(value)
        return None
    if key and _is_path_key(key):
        return None
    if value is None or isinstance(value, (bool, int, str)):
        if isinstance(value, str) and _DRIVE_PATH.search(value):
            return _DRIVE_PATH.sub("[server-path-redacted]", value)
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Path):
        return None
    if is_dataclass(value):
        return to_browser_value(asdict(value))
    if hasattr(value, "model_dump"):
        return to_browser_value(value.model_dump(mode="python"))
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            if value.__class__.__module__.startswith("pandas"):
                if value.__class__.__name__ == "DataFrame":
                    return [to_browser_value(row) for row in value.to_dict(orient="records")]
                if value.__class__.__name__ == "Series":
                    return to_browser_value(value.to_dict())
            return to_browser_value(value.to_dict())
        except Exception:
            pass
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for raw_key, item in value.items():
            item_key = str(raw_key)
            converted = to_browser_value(item, key=item_key)
            if _is_path_key(item_key):
                continue
            if _is_safe_status_container(item_key):
                output[item_key] = converted
                continue
            if _is_sensitive_key(item_key) and not item_key.lower().endswith("_configured"):
                continue
            output[item_key] = converted
        return output
    if isinstance(value, (list, tuple, set)):
        return [to_browser_value(item) for item in value]
    if hasattr(value, "item"):
        try:
            return to_browser_value(value.item())
        except Exception:
            pass
    return str(value)


def table_payload(value: Any) -> dict[str, Any]:
    records = to_browser_value(value)
    if not isinstance(records, list):
        records = []
    columns: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        for item_key, item_value in record.items():
            if item_key in seen:
                continue
            seen.add(item_key)
            data_type = (
                "number"
                if isinstance(item_value, (int, float)) and not isinstance(item_value, bool)
                else "boolean"
                if isinstance(item_value, bool)
                else "string"
            )
            columns.append({"key": item_key, "title": item_key, "data_type": data_type})
    return {"columns": columns, "records": records, "total": len(records)}
