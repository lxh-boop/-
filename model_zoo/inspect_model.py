from __future__ import annotations

import argparse
import json
from pathlib import Path

from .metadata import detect_file_format, get_model_metadata
from .registry import get_model_entry, list_model_names


def inspect_model(model: str) -> dict:
    entry = get_model_entry(model)
    meta = get_model_metadata(entry.name) or {}
    local_path = Path(meta.get("local_path") or entry.local_path)
    files = []

    if local_path.exists():
        files = [
            str(p.relative_to(local_path))
            for p in local_path.rglob("*")
            if p.is_file()
        ]

    return {
        "name": entry.name,
        "provider": entry.provider,
        "hf_repo": entry.hf_repo,
        "local_path": str(local_path),
        "exists": local_path.exists(),
        "file_format": detect_file_format(local_path),
        "file_count": len(files),
        "file_sample": files[:50],
        "metadata": meta,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, choices=list_model_names())
    args = parser.parse_args()
    print(json.dumps(inspect_model(args.model), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
