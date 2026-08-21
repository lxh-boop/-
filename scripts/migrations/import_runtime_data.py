from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import AGENT_QUANT_DB_PATH, OUTPUT_DIR
from database.runtime_data_import import import_runtime_output_tree


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Idempotently import live CSV/JSON runtime data into SQLite."
    )
    parser.add_argument("--db-path", default=str(AGENT_QUANT_DB_PATH))
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--user", action="append", dest="users")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = import_runtime_output_tree(
        args.output_dir,
        db_path=args.db_path,
        users=args.users,
        force=args.force,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "validated" else 1


if __name__ == "__main__":
    raise SystemExit(main())
