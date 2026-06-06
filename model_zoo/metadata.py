from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .registry import EXTERNAL_ZOO_DIR, ModelZooEntry, get_model_entry, list_model_entries


METADATA_PATH = EXTERNAL_ZOO_DIR / "metadata.json"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def ensure_zoo_dirs() -> None:
    EXTERNAL_ZOO_DIR.mkdir(parents=True, exist_ok=True)
    for entry in list_model_entries():
        (EXTERNAL_ZOO_DIR / entry.family).mkdir(parents=True, exist_ok=True)


def load_metadata() -> dict:
    ensure_zoo_dirs()
    if not METADATA_PATH.exists():
        return {
            "version": 1,
            "updated_at": _now(),
            "models": [],
        }
    try:
        return json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {
            "version": 1,
            "updated_at": _now(),
            "models": [],
        }


def save_metadata(metadata: dict) -> Path:
    ensure_zoo_dirs()
    metadata["updated_at"] = _now()
    METADATA_PATH.write_text(
        json.dumps(_jsonable(metadata), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return METADATA_PATH


def list_metadata_models() -> list[dict]:
    return list(load_metadata().get("models", []))


def get_model_metadata(name: str) -> dict | None:
    key = get_model_entry(name).name
    for item in list_metadata_models():
        if item.get("name") == key:
            return dict(item)
    return None


def detect_file_format(local_path: str | Path) -> str:
    path = Path(local_path)
    if not path.exists():
        return "missing"
    names = [p.name for p in path.rglob("*") if p.is_file()]
    if any(name.endswith(".safetensors") for name in names):
        return "huggingface_safetensors"
    if any(name.endswith(".bin") for name in names):
        return "huggingface_bin"
    if any(name.endswith((".pth", ".pt")) for name in names):
        return "pytorch_checkpoint"
    if any(name in {"config.json", "model_config.json"} for name in names):
        return "huggingface"
    return "directory"


def upsert_model_metadata(
    entry: ModelZooEntry | str,
    *,
    status: str,
    local_path: str | Path | None = None,
    extra: dict | None = None,
) -> dict:
    if isinstance(entry, str):
        entry = get_model_entry(entry)

    metadata = load_metadata()
    models = [dict(item) for item in metadata.get("models", [])]
    local_path = Path(local_path or entry.local_path)

    item = entry.to_metadata()
    item.update(
        {
            "local_path": str(local_path),
            "file_format": detect_file_format(local_path),
            "status": status,
            "updated_at": _now(),
        }
    )
    if extra:
        item.update(extra)

    replaced = False
    for idx, old in enumerate(models):
        if old.get("name") == entry.name:
            models[idx] = item
            replaced = True
            break
    if not replaced:
        models.append(item)

    metadata["models"] = models
    save_metadata(metadata)
    return item


def bootstrap_registered_metadata() -> Path:
    metadata = load_metadata()
    known = {item.get("name") for item in metadata.get("models", [])}
    models = list(metadata.get("models", []))

    for entry in list_model_entries():
        if entry.name in known:
            continue
        item = entry.to_metadata()
        item.update(
            {
                "status": "registered",
                "file_format": detect_file_format(entry.local_path),
                "updated_at": _now(),
            }
        )
        models.append(item)

    metadata["models"] = models
    return save_metadata(metadata)


if __name__ == "__main__":
    print(bootstrap_registered_metadata())
