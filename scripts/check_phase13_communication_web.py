from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from urllib.request import urlopen

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


PAGES = [
    "首页 / 预测排名",
    "AI Agent",
    "AI 模拟盘",
    "系统监控",
]


def _health(url: str = "http://127.0.0.1:8501/_stcore/health") -> str:
    with urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8", errors="replace")


def _page_check(page_name: str) -> dict[str, object]:
    at = AppTest.from_file(str(ROOT / "app.py"))
    at.run(timeout=60)
    at.radio[0].set_value(page_name).run(timeout=90)
    return {
        "page": page_name,
        "exceptions": len(at.exception),
        "error_count": len(at.error),
    }


def main() -> int:
    result = {
        "health": _health(),
        "pages": [_page_check(page) for page in PAGES],
        "manual_checklist": [
            "AI Agent can accept a question",
            "message trace summary is visible after a run",
            "no confirmation_token/API key/db path/stack is visible",
        ],
        "message_log_root_exists": (Path("outputs") / "message_logs").exists(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    failed = result["health"] != "ok" or any(item["exceptions"] or item["error_count"] for item in result["pages"])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
