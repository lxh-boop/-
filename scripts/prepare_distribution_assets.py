from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_version import APP_NAME, APP_VERSION
from database.connection import initialize_database
from runtime_paths import (
    get_database_dir,
    get_logs_dir,
    get_outputs_dir,
    get_project_root,
    get_resource_root,
    get_user_data_root,
    is_frozen_app,
)


def _repo_root() -> Path:
    return PROJECT_ROOT


def _expected_frozen_user_root() -> Path:
    import os

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "StockDailyApp"
    return Path.home() / "AppData" / "Local" / "StockDailyApp"


def main() -> int:
    root = _repo_root()
    migrations = root / "database" / "migrations"
    resources = root / "resources"
    probe_dir = root / "build" / "distribution_probe"
    probe_db = probe_dir / "agent_quant_probe.db"
    live_db = root / "data" / "agent_quant.db"
    frozen_user_root = _expected_frozen_user_root()

    print("=" * 80)
    print(f"[Distribution Assets] {APP_NAME} {APP_VERSION}")
    print(f"[Mode] {'frozen' if is_frozen_app() else 'source'}")
    print(f"[Project Root] {get_project_root()}")
    print(f"[Resource Root] {get_resource_root()}")
    print(f"[User Data Root] {get_user_data_root()}")
    print(f"[Development Live DB] {live_db}")
    print(f"[Current Mode DB Dir] {get_database_dir()}")
    print(f"[Current Mode Outputs Dir] {get_outputs_dir()}")
    print(f"[Current Mode Logs Dir] {get_logs_dir()}")
    print(f"[Frozen User Data Root Expected] {frozen_user_root}")
    print(f"[Frozen DB Expected] {frozen_user_root / 'database' / 'agent_quant.db'}")
    print(f"[Frozen Config Expected] {frozen_user_root / 'config' / 'local_app_config.json'}")
    print("=" * 80)

    required = [
        root / "app.py",
        root / "desktop_launcher.py",
        root / "stock_daily_app.spec",
        root / ".streamlit" / "config.toml",
        migrations,
        resources,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        print("[Error] Missing required distribution inputs:")
        print(json.dumps(missing, ensure_ascii=False, indent=2))
        return 1

    migration_files = sorted(migrations.glob("*.sql"))
    if not migration_files:
        print(f"[Error] No migration files found: {migrations}")
        return 1

    print(f"[Migrations] {len(migration_files)} files")
    print("[Database] Initializing a probe database copy under build/ only.")
    print(f"[Database] Source live database is not modified: {live_db}")
    print(f"[Database] Probe database: {probe_db}")
    probe_dir.mkdir(parents=True, exist_ok=True)
    if probe_db.exists():
        probe_db.unlink()
    initialize_database(probe_db)

    root_sensitive = [
        root / ".env",
        root / "local_app_config.json",
        root / "local_config.json",
    ]
    present_sensitive = [str(path) for path in root_sensitive if path.exists()]
    if present_sensitive:
        print("[Sensitive Local Files] Present in development tree, intentionally not listed in spec datas:")
        print(json.dumps(present_sensitive, ensure_ascii=False, indent=2))

    print("[Package Resources]")
    print(json.dumps({
        "app_script": "app.py",
        "streamlit_config": ".streamlit/config.toml",
        "database_migrations": "database/migrations",
        "database_seed": "database/seed",
        "resources": "resources",
        "bundled_demo_data": [
            "data/ -> bundled_seed/data/",
            "models/ -> bundled_seed/models/",
            "outputs/ -> bundled_seed/outputs/",
        ],
        "excluded_sensitive_files": [
            "logs/",
            "runtime/",
            "local_app_config.json",
            "config/local_app_config.json",
            ".env",
        ],
    }, ensure_ascii=False, indent=2))
    print("[OK] Distribution asset preparation checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
