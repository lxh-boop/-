from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_version import APP_NAME, APP_VERSION


SOURCE_PATH_MARKER = b"D:\\stock_daily_app"
SENSITIVE_NAMES = {
    ".env",
    "local_app_config.json",
    "local_config.json",
    "agent_quant.db",
    "news_mapping.db",
}
ALLOWED_BUNDLED_DEMO_DB_NAMES = {
    "agent_quant.db",
    "news_mapping.db",
}
SENSITIVE_TOP_LEVEL_DIRS = {"outputs", "logs", "runtime", ".git", "__pycache__", ".pytest_cache"}


def _repo_root() -> Path:
    return PROJECT_ROOT


def _scan_source_path(path: Path) -> bool:
    try:
        with path.open("rb") as file:
            return SOURCE_PATH_MARKER in file.read()
    except Exception:
        return False


def main() -> int:
    root = _repo_root()
    dist_root = root / "dist" / APP_NAME
    exe_path = dist_root / f"{APP_NAME}.exe"
    internal_root = dist_root / "_internal"
    seed_root = internal_root / "bundled_seed"
    installer_path = root / "installer_output" / f"{APP_NAME}_Setup_{APP_VERSION}.exe"

    errors: list[str] = []
    warnings: list[str] = []

    if not exe_path.exists():
        errors.append(f"missing executable: {exe_path}")
    if not (internal_root / "database" / "migrations").exists():
        errors.append(f"missing bundled migrations: {internal_root / 'database' / 'migrations'}")
    if not (internal_root / "resources").exists():
        errors.append(f"missing bundled resources: {internal_root / 'resources'}")
    if not seed_root.exists():
        errors.append(f"missing bundled demo seed: {seed_root}")
    else:
        expected_seed_files = [
            seed_root / "data" / "agent_quant.db",
            seed_root / "models" / "external_zoo" / "metadata.json",
            seed_root / "outputs" / "ranking_latest.csv",
        ]
        for path in expected_seed_files:
            if not path.exists():
                errors.append(f"missing bundled demo file: {path}")

    if dist_root.exists():
        for path in dist_root.rglob("*"):
            rel = path.relative_to(dist_root)
            lowered_name = path.name.lower()
            top_level = rel.parts[0].lower() if rel.parts else ""
            allowed_bundled_demo_db = (
                len(rel.parts) >= 4
                and rel.parts[0] == "_internal"
                and rel.parts[1] == "bundled_seed"
                and rel.parts[2] == "data"
                and lowered_name in ALLOWED_BUNDLED_DEMO_DB_NAMES
            )
            if lowered_name in SENSITIVE_NAMES and not allowed_bundled_demo_db:
                errors.append(f"sensitive file included: {rel}")
            if top_level in SENSITIVE_TOP_LEVEL_DIRS:
                errors.append(f"runtime/personal directory included: {rel}")
            if path.is_file() and path.stat().st_size <= 100 * 1024 * 1024 and _scan_source_path(path):
                errors.append(f"source absolute path marker found in bundled file: {rel}")
    else:
        errors.append(f"missing distribution directory: {dist_root}")

    if not installer_path.exists():
        warnings.append(f"installer not found yet: {installer_path}")

    result = {
        "app": APP_NAME,
        "version": APP_VERSION,
        "dist_root": str(dist_root),
        "exe": str(exe_path),
        "installer": str(installer_path),
        "errors": errors,
        "warnings": warnings,
        "manual_checks": [
            "Install on a clean Windows user profile.",
            "Launch from the Start menu shortcut.",
            "Confirm Streamlit listens on 127.0.0.1 and a dynamic port.",
            "Close the desktop window and confirm the Streamlit child process exits.",
            "Confirm existing %LOCALAPPDATA%\\StockDailyApp user data is preserved during upgrade and uninstall.",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
