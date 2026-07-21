from __future__ import annotations

import argparse
from pathlib import Path

FORBIDDEN = {
    "LayeredMemoryService",
    "retrieve_layered_memory",
    "memory_view_for_agent",
    "layered_agent_memory",
    "build_agent_context",
    "gather_context_items",
    "from agent.context.schemas",
    "from .legacy import",
    "from .working_memory import",
    "from agent.memory.working_memory import",
    "WorkingMemory(",
    "to_legacy_memory_item",
    "from_legacy_memory_item",
}

SKIP_PARTS = {
    ".git",
    "__pycache__",
    "outputs",
    "data",
    "models",
    "logs",
    "docs",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    scan_roots = [root / "agent", root / "app", root / "portfolio", root / "pipelines"]
    violations: list[str] = []

    for scan_root in scan_roots:
        if not scan_root.exists():
            continue
        for path in scan_root.rglob("*.py"):
            if any(part in SKIP_PARTS for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in sorted(FORBIDDEN):
                if token in text:
                    violations.append(f"{path.relative_to(root)}: {token}")

    legacy_path = root / "agent" / "memory" / "legacy.py"
    if legacy_path.exists():
        violations.append("agent/memory/legacy.py: file must be removed")

    working_path = root / "agent" / "memory" / "working_memory.py"
    if working_path.exists():
        violations.append(
            "agent/memory/working_memory.py: ContextBundle is the only run working memory"
        )

    if violations:
        print("Legacy Memory runtime violations:")
        for item in violations:
            print(f"- {item}")
        return 1
    print("OK: no legacy Memory/context runtime entry points found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
