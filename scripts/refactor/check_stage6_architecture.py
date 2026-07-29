from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


def main() -> int:
    violations: list[str] = []
    if not FRONTEND.is_dir():
        violations.append("frontend directory is missing")

    forbidden_patterns = {
        "Windows absolute path": re.compile(r"[A-Za-z]:\\"),
        "direct SQLite access": re.compile(r"sqlite3?|task_runtime\.sqlite", re.I),
        "Neo4j password": re.compile(r"NEO4J_PASSWORD", re.I),
        "LLM credential": re.compile(r"llm_api_key|tushare_token|api[_-]?key\s*[:=]", re.I),
        "direct backend container URL": re.compile(r"http://api:8010", re.I),
    }

    for python_file in FRONTEND.rglob("*.py"):
        violations.append(f"frontend contains Python source: {python_file.relative_to(ROOT).as_posix()}")

    checked = 0
    for path in FRONTEND.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".ts", ".tsx", ".js", ".jsx", ".json", ".css", ".html"}:
            continue
        if "node_modules" in path.parts or path.name == "package-lock.json":
            continue
        checked += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(ROOT).as_posix()
        for label, pattern in forbidden_patterns.items():
            if pattern.search(text):
                violations.append(f"{relative}: {label}")

    nginx = (FRONTEND / "nginx.conf").read_text(encoding="utf-8") if (FRONTEND / "nginx.conf").exists() else ""
    for marker in ("proxy_pass http://api:8010", "proxy_buffering off", "X-Accel-Buffering"):
        if marker not in nginx:
            violations.append(f"nginx SSE/API marker missing: {marker}")

    overlay = ROOT / "docker-compose.react-preview.yml"
    compose = ROOT / "docker-compose.yml"
    if overlay.exists():
        text = overlay.read_text(encoding="utf-8")
        if "react-preview:" not in text:
            violations.append("react-preview service missing")
    elif not compose.exists():
        violations.append("neither preview overlay nor production compose exists")
    else:
        text = compose.read_text(encoding="utf-8")
        if "  frontend:" not in text:
            violations.append("production frontend service missing")
        if "  streamlit:" in text or "  react-preview:" in text:
            violations.append("retired frontend service remains in production compose")

    report = {"stage": "6.1", "checked_frontend_files": checked, "violation_count": len(violations), "violations": violations}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
