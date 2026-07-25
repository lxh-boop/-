from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import requests
from playwright.sync_api import Page, sync_playwright


def record(results: list[dict[str, Any]], name: str, success: bool, detail: str = "") -> None:
    results.append({"name": name, "success": bool(success), "detail": str(detail)})


def screenshot(page: Page, directory: Path, name: str) -> None:
    page.screenshot(path=str(directory / f"{name}.png"), full_page=True)


def wait_for_text(page: Page, text: str, timeout: int = 90_000) -> bool:
    try:
        page.get_by_text(text, exact=False).first.wait_for(timeout=timeout)
        return True
    except Exception:
        return False


def wait_for_task_terminal(page: Page, timeout: int = 90_000) -> str:
    deadline = time.monotonic() + timeout / 1000
    terminal = {"succeeded", "failed", "cancelled", "timed_out", "interrupted"}
    while time.monotonic() < deadline:
        tags = page.locator('[data-testid="task-status"]')
        if tags.count():
            status = tags.first.inner_text().strip()
            if status in terminal:
                return status
        page.wait_for_timeout(500)
    raise RuntimeError("等待 React 任务终态超时")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:3000")
    parser.add_argument("--api-url", default="http://127.0.0.1:8010")
    parser.add_argument("--streamlit-url", default="http://127.0.0.1:8501")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    output = Path(args.output_dir)
    screenshots = output / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    try:
        response = requests.get(f"{args.api_url}/api/v1/health", timeout=15)
        payload = response.json()
        data = payload.get("data") or {}
        record(results, "FastAPI 健康检查", response.status_code == 200 and payload.get("success") and data.get("version") == "4.0.0", f"status={response.status_code}; version={data.get('version')}; deployment={data.get('deployment_mode')}")
    except Exception as exc:
        record(results, "FastAPI 健康检查", False, f"{type(exc).__name__}: {exc}")

    try:
        response = requests.get(f"{args.streamlit_url}/_stcore/health", timeout=15)
        record(results, "Streamlit 对照基线仍可用", response.status_code == 200, f"status={response.status_code}")
    except Exception as exc:
        record(results, "Streamlit 对照基线仍可用", False, f"{type(exc).__name__}: {exc}")

    console_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=not args.headed)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.set_default_timeout(60_000)
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: console_errors.append(str(error)))
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=120_000)
            opened = wait_for_text(page, "阶段 6 React 预览", 120_000)
            connected = wait_for_text(page, "FastAPI 已连接", 120_000)
            record(results, "React 预览首页可打开", opened, "已找到 React 标题" if opened else "未找到 React 标题")
            record(results, "React 经 Nginx 连接 FastAPI", connected, "FastAPI 已连接" if connected else "未显示连接状态")
            record(results, "React 显示 API 合同基线", wait_for_text(page, "公共合同", 30_000) and wait_for_text(page, "4.0.0", 30_000), "公共合同和 API 版本已显示")
            screenshot(page, screenshots, "01_react_health")

            page.get_by_text("任务运行时", exact=True).click()
            runtime_loaded = wait_for_text(page, "Task API 与 SSE 验证", 60_000)
            record(results, "React 任务页面可打开", runtime_loaded)

            button = page.get_by_test_id("run-diagnostic-task")
            button.click()
            task_created = wait_for_text(page, "task_", 30_000)
            record(results, "React 提交 Task API", task_created, "获得 task_id" if task_created else "未显示 task_id")
            status = wait_for_task_terminal(page, 90_000)
            event_text = page.get_by_test_id("event-count").inner_text()
            event_count = int(event_text.split("：")[-1]) if "：" in event_text else 0
            record(results, "React SSE 任务生命周期", status == "succeeded" and event_count >= 3, f"status={status}; events={event_count}")
            screenshot(page, screenshots, "02_react_task_succeeded")

            page.reload(wait_until="domcontentloaded", timeout=120_000)
            recovered_page = wait_for_text(page, "Task API 与 SSE 验证", 60_000)
            recovered_status = wait_for_task_terminal(page, 30_000) if recovered_page else ""
            recovered_task_id = page.get_by_text("task_", exact=False).count() > 0
            record(results, "React 刷新后恢复 task_id 与终态", recovered_page and recovered_status == "succeeded" and recovered_task_id, f"status={recovered_status}; task_id_visible={recovered_task_id}")
            screenshot(page, screenshots, "03_react_task_recovered")
        except Exception as exc:
            record(results, "React Chrome 执行", False, f"{type(exc).__name__}: {exc}")
            try:
                screenshot(page, screenshots, "99_failure")
            except Exception:
                pass
        finally:
            browser.close()

    meaningful_errors = [item for item in console_errors if "favicon" not in item.lower()]
    record(results, "React 控制台无未捕获错误", not meaningful_errors, " | ".join(meaningful_errors[-10:]))

    passed = sum(1 for item in results if item["success"])
    failed = len(results) - passed
    report = {"passed": passed, "failed": failed, "results": results}
    (output / "browser_test_result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Stage 6.1 Browser Acceptance", "", f"- Passed: {passed}", f"- Failed: {failed}", ""]
    lines.extend(f"- [{'PASS' if item['success'] else 'FAIL'}] {item['name']} — {item['detail']}" for item in results)
    (output / "acceptance_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
