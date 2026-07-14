from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any


DEFAULT_PAGES = ["首页", "AI Agent", "AI 模拟盘", "系统监控"]
DEFAULT_AGENT_INPUTS = [
    "查看我的当前持仓",
    "分析当前组合风险",
    "给我一个调仓建议",
    "查看系统状态",
]
CHECKLIST = [
    "页面是否打开",
    "是否有 Traceback",
    "是否有 ModuleNotFoundError",
    "是否有 NameError",
    "是否有 KeyError",
    "是否能输入 AI Agent 问题",
    "是否能返回结果",
    "是否能生成 proposal",
    "是否显示 token 原文",
]


def _fetch_text(url: str, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "phase12-context-web-check"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
        return int(response.status), body


def build_web_check_payload(base_url: str, timeout: float) -> dict[str, Any]:
    base = str(base_url or "").rstrip("/")
    health_url = f"{base}/_stcore/health"
    payload: dict[str, Any] = {
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "base_url": base,
        "health_url": health_url,
        "health_status": "failed",
        "health_body": "",
        "pages": DEFAULT_PAGES,
        "agent_inputs": DEFAULT_AGENT_INPUTS,
        "manual_checklist": CHECKLIST,
        "browser_required": True,
        "notes": (
            "This script verifies Streamlit health and prints the Phase 12 browser "
            "checklist. Full Streamlit interaction must still be verified in a real browser."
        ),
    }
    try:
        status, body = _fetch_text(health_url, timeout)
        payload["health_http_status"] = status
        payload["health_body"] = body.strip()[:120]
        payload["health_status"] = "ok" if status == 200 and body.strip().lower() == "ok" else "unexpected"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        payload["health_error"] = f"{type(exc).__name__}: {exc}"
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 12 Context UI web health/checklist helper")
    parser.add_argument("--base-url", default="http://127.0.0.1:8501")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    payload = build_web_check_payload(args.base_url, args.timeout)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("health_status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
