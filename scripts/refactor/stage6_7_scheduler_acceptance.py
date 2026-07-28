from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Any


def fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def record(results: list[dict[str, Any]], name: str, passed: bool, detail: str) -> None:
    results.append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:3000")
    parser.add_argument("--api-url", default="http://127.0.0.1:8010")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--headed", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = Path(args.output_dir)
    shots = output / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    payload = fetch_json(f"{args.api_url}/api/v1/web/settings")
    data = payload.get("data") or {}
    scheduler = data.get("scheduler") or {}
    required = {
        "enabled",
        "hour",
        "minute",
        "runtime_running",
        "job_registered",
        "next_run_time",
        "expected_signal_date",
        "latest_signal_date",
        "stale",
        "last_status",
    }
    missing = sorted(required - set(scheduler))
    record(results, "Settings API exposes real scheduler status", not missing, f"missing={missing}")
    if scheduler.get("enabled"):
        record(
            results,
            "Enabled scheduler is registered in the FastAPI process",
            bool(scheduler.get("runtime_running") and scheduler.get("job_registered")),
            f"runtime_running={scheduler.get('runtime_running')}; job_registered={scheduler.get('job_registered')}",
        )
    else:
        record(results, "Disabled scheduler is reported explicitly", True, "enabled=false")

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not args.headed)
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.goto(f"{args.url}/settings", wait_until="domcontentloaded", timeout=120_000)
            page.get_by_text("每日自动更新", exact=False).first.wait_for(state="visible", timeout=120_000)
            page.get_by_text("自动更新运行状态", exact=False).first.wait_for(state="visible", timeout=120_000)
            page.get_by_role("button", name="立即运行完整日更", exact=True).wait_for(state="visible", timeout=120_000)
            body = page.locator("body").inner_text()
            markers = [
                "启用 FastAPI 常驻自动更新",
                "API 启动后自动补跑缺失交易日",
                "应有信号日",
                "当前信号日",
                "立即运行完整日更",
            ]
            found = [item for item in markers if item in body]
            record(results, "Settings page renders scheduler controls and status", len(found) == len(markers), f"markers={found}")
            page.screenshot(path=str(shots / "01_scheduler_settings.png"), full_page=True)
            browser.close()
    except Exception as exc:
        record(results, "Settings page renders scheduler controls and status", False, f"{type(exc).__name__}: {exc}")

    passed = sum(1 for item in results if item["passed"])
    failed = len(results) - passed
    report = {"passed": passed, "failed": failed, "results": results, "scheduler": scheduler}
    (output / "scheduler_acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Stage 6.7 Scheduler Acceptance", "", f"Passed: {passed}", f"Failed: {failed}", ""]
    lines.extend(f"- [{'x' if item['passed'] else ' '}] {item['name']}: {item['detail']}" for item in results)
    (output / "acceptance_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
