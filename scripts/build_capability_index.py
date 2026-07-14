from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.capability_index import build_trusted_capability_index
from runtime_paths import get_runtime_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the trusted read-only Agent capability index.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path. Defaults to runtime/capability_index/capability_index_latest.json.",
    )
    parser.add_argument(
        "--include-mcp",
        action="store_true",
        help="Include MCP tools that are already exposed through the authorized MCP registry bridge.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    index = build_trusted_capability_index(include_mcp=bool(args.include_mcp))
    output = args.output
    if output is None:
        output = get_runtime_dir() / "capability_index" / "capability_index_latest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(index.to_dict(agent_view=False), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(
        {
            "output": str(output),
            "index_version": index.index_version,
            "record_count": len(index.records),
            "content_hash": index.content_hash,
        },
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
