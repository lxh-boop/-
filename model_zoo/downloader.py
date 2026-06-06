from __future__ import annotations

import argparse
import json
from pathlib import Path

from .metadata import bootstrap_registered_metadata, upsert_model_metadata
from .registry import EXTERNAL_ZOO_DIR, get_model_entry, list_model_names


def _require_huggingface_hub():
    try:
        from huggingface_hub import HfApi, snapshot_download
    except Exception as exc:
        raise RuntimeError(
            "缺少 huggingface_hub，请先运行：pip install huggingface_hub"
        ) from exc
    return HfApi, snapshot_download


def _is_downloaded(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    return any(p.is_file() for p in path.rglob("*"))


def download_model(
    model: str,
    output_dir: str | Path = EXTERNAL_ZOO_DIR,
    force: bool = False,
) -> dict:
    entry = get_model_entry(model)
    output_dir = Path(output_dir)
    local_path = output_dir / entry.family / entry.local_subdir

    bootstrap_registered_metadata()

    if _is_downloaded(local_path) and not force:
        item = upsert_model_metadata(
            entry,
            status="downloaded",
            local_path=local_path,
            extra={
                "download_action": "already_exists",
                "safe_loading_note": "Hugging Face snapshot already present; no repository code executed.",
            },
        )
        return item

    HfApi, snapshot_download = _require_huggingface_hub()
    api = HfApi()

    try:
        info = api.model_info(entry.hf_repo)
        siblings = [s.rfilename for s in info.siblings or []]
        license_name = None
        if getattr(info, "card_data", None) is not None:
            license_name = getattr(info.card_data, "license", None)
        if not license_name:
            license_name = entry.license
    except Exception as exc:
        raise RuntimeError(f"读取 Hugging Face 模型信息失败：{entry.hf_repo}，原因：{exc}") from exc

    local_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        snapshot_download(
            repo_id=entry.hf_repo,
            local_dir=str(local_path),
        )
    except Exception as exc:
        upsert_model_metadata(
            entry,
            status="download_failed",
            local_path=local_path,
            extra={
                "error": str(exc),
                "hf_repo": entry.hf_repo,
            },
        )
        raise RuntimeError(f"下载模型失败：{entry.hf_repo}，原因：{exc}") from exc

    item = upsert_model_metadata(
        entry,
        status="downloaded",
        local_path=local_path,
        extra={
            "hf_repo": entry.hf_repo,
            "license": license_name or entry.license,
            "download_action": "snapshot_download",
            "files": siblings[:200],
            "safe_loading_note": (
                "Downloaded with huggingface_hub.snapshot_download; no repository training "
                "script or remote code was executed by the downloader."
            ),
        },
    )
    return item


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download external time-series model snapshots.")
    parser.add_argument("--model", required=True, choices=list_model_names())
    parser.add_argument("--output-dir", default=str(EXTERNAL_ZOO_DIR))
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        item = download_model(args.model, output_dir=args.output_dir, force=args.force)
        print(json.dumps(item, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"[Download Failed] {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
