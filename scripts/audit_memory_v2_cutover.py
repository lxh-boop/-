from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Memory V2 context snapshots.")
    parser.add_argument("--outputs", default="outputs")
    parser.add_argument("--user-id", default="")
    args = parser.parse_args()

    root = Path(args.outputs) / "context_snapshots"
    if args.user_id:
        roots = [root / args.user_id]
    else:
        roots = [path for path in root.iterdir()] if root.exists() else []

    rows: list[dict[str, Any]] = []
    for user_root in roots:
        if not user_root.exists():
            continue
        for path in user_root.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            memory = payload.get("memory_context") if isinstance(payload, dict) else {}
            if not isinstance(memory, dict):
                continue
            rows.append(
                {
                    "file": str(path),
                    "retrieval_id": memory.get("retrieval_id"),
                    "candidate_count": memory.get("candidate_count", 0),
                    "threshold_pass_count": memory.get("threshold_pass_count", 0),
                    "selected_count": memory.get("selected_count", 0),
                    "relevance_threshold": memory.get("relevance_threshold", 0),
                    "token_budget": memory.get("token_budget", 0),
                    "token_used": memory.get("token_used", 0),
                }
            )

    print(json.dumps({"snapshot_count": len(rows), "snapshots": rows[-50:]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
