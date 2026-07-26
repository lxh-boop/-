from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import requests
from playwright.sync_api import Page, sync_playwright


def record(results: list[dict[str, Any]], name: str, success: bool, detail: str = "") -> None:
    results.append({"name": name, "success": bool(success), "detail": str(detail)})


def screenshot(page: Page, directory: Path, name: str) -> None:
    page.screenshot(path=str(directory / f"{name}.png"), full_page=True)


def get_envelope(api_url: str, path: str) -> tuple[bool, str]:
    try:
        response = requests.get(f"{api_url}{path}", timeout=90)
        payload = response.json()
        error = payload.get("error") or {}
        ok = response.status_code == 200 and payload.get("success") is True
        return ok, f"status={response.status_code}; success={payload.get('success')}; error={error.get('code', '')}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def visible_texts(page: Page, selectors: list[str]) -> list[str]:
    found: list[str] = []
    for selector in selectors:
        locator = page.locator(selector)
        for index in range(locator.count()):
            item = locator.nth(index)
            try:
                if item.is_visible():
                    text = item.inner_text().strip()
                    if text:
                        found.append(text)
            except Exception:
                continue
    return found


def wait_for_page_ready(page: Page, heading: str, timeout: int = 180_000) -> tuple[bool, str]:
    """Wait for the real page body, not matching text in the sidebar/header."""
    try:
        page.get_by_role("heading", name=heading, exact=True).first.wait_for(state="visible", timeout=timeout)
        loading = page.locator(".page-loading")
        if loading.count():
            loading.first.wait_for(state="hidden", timeout=timeout)
        page.wait_for_timeout(500)

        loading_visible = any(loading.nth(i).is_visible() for i in range(loading.count()))
        errors = visible_texts(
            page,
            [
                ".ant-alert-error",
                ".ant-result-error",
                ".error-boundary",
            ],
        )
        body_text = page.locator("body").inner_text()
        known_error_markers = [
            "页面渲染失败",
            "只读首页加载失败",
            "模型指标加载失败",
            "模型搜索结果加载失败",
            "回测数据加载失败",
            "新闻事件加载失败",
            "设置读取失败",
            "系统监控加载失败",
            "FastAPI 连接失败",
        ]
        marker_hits = [marker for marker in known_error_markers if marker in body_text]
        ready = not loading_visible and not errors and not marker_hits
        detail = (
            f"heading={heading}; loading_visible={loading_visible}; "
            f"errors={errors[-3:]}; marker_hits={marker_hits}"
        )
        return ready, detail
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


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

    ok, detail = get_envelope(args.api_url, "/api/v1/health")
    record(results, "FastAPI 健康检查", ok, detail)
    try:
        response = requests.get(f"{args.streamlit_url}/_stcore/health", timeout=15)
        record(results, "Streamlit 对照基线仍可用", response.status_code == 200, f"status={response.status_code}")
    except Exception as exc:
        record(results, "Streamlit 对照基线仍可用", False, f"{type(exc).__name__}: {exc}")

    try:
        response = requests.get(f"{args.api_url}/openapi.json", timeout=30)
        paths = response.json().get("paths") or {}
        web_paths = {path: methods for path, methods in paths.items() if path.startswith("/api/v1/web/")}
        all_get_only = len(web_paths) >= 23 and all(
            set(methods).issubset({"get", "parameters"}) for methods in web_paths.values()
        )
        record(results, "只读 REST 路由已注册", all_get_only, f"web_paths={len(web_paths)}; get_only={all_get_only}")
    except Exception as exc:
        record(results, "只读 REST 路由已注册", False, f"{type(exc).__name__}: {exc}")

    api_cases = [
        ("Dashboard Summary", "/api/v1/web/dashboard/summary"),
        ("Dashboard Rankings", "/api/v1/web/dashboard/rankings?limit=20"),
        ("Model Metrics", "/api/v1/web/models/metrics"),
        ("Model Search Results", "/api/v1/web/models/search-results"),
        ("Backtest Read", "/api/v1/web/backtests/latest"),
        ("News Read", "/api/v1/web/news/events?limit=20"),
        ("Public Settings", "/api/v1/web/settings"),
        ("Monitor Services", "/api/v1/web/monitor/services"),
    ]
    for name, path in api_cases:
        ok, detail = get_envelope(args.api_url, path)
        record(results, f"只读 API：{name}", ok, detail)

    try:
        response = requests.get(f"{args.api_url}/api/v1/web/settings", timeout=30)
        payload = response.json()
        data = payload.get("data") or {}
        credentials = data.get("credentials")
        settings_contract_ok = (
            response.status_code == 200
            and payload.get("success") is True
            and isinstance(credentials, dict)
            and isinstance(credentials.get("tushare_configured"), bool)
            and isinstance(credentials.get("llm_configured"), bool)
            and not any(key in credentials for key in ("api_key", "token", "tushare_token", "password", "secret"))
        )
        record(
            results,
            "公开设置 DTO 包含安全配置状态",
            settings_contract_ok,
            f"status={response.status_code}; credential_keys={sorted(credentials) if isinstance(credentials, dict) else []}",
        )
    except Exception as exc:
        record(results, "公开设置 DTO 包含安全配置状态", False, f"{type(exc).__name__}: {exc}")

    console_errors: list[str] = []
    page_cases = [
        ("01_dashboard", "/dashboard", "首页 / 预测排名"),
        ("02_stock", "/stocks", "个股详情"),
        ("03_metrics", "/models/metrics", "模型指标"),
        ("04_model_search", "/models/search", "模型搜索与回测"),
        ("05_backtest", "/backtests", "回测分析"),
        ("06_news", "/news", "新闻事件"),
        ("07_settings", "/settings", "系统设置"),
        ("08_monitor", "/monitor", "系统监控"),
        ("09_platform", "/platform", "React 基础设施与公共合同"),
        ("10_runtime", "/runtime", "Task API 与 SSE 验证"),
    ]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=not args.headed)
        page = browser.new_page(viewport={"width": 1680, "height": 1050})
        page.set_default_timeout(90_000)
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: console_errors.append(str(error)))
        try:
            for shot, route, heading in page_cases:
                page.goto(f"{args.url}{route}", wait_until="domcontentloaded", timeout=120_000)
                connected = False
                try:
                    page.get_by_text("FastAPI 已连接", exact=False).first.wait_for(state="visible", timeout=90_000)
                    connected = True
                except Exception:
                    connected = False
                ready, ready_detail = wait_for_page_ready(page, heading)
                record(
                    results,
                    f"React 页面：{heading}",
                    connected and ready,
                    f"api_connected={connected}; route={route}; {ready_detail}",
                )
                screenshot(page, screenshots, shot)

            page.goto(f"{args.url}/news", wait_until="domcontentloaded", timeout=120_000)
            first_ready, _ = wait_for_page_ready(page, "新闻事件")
            page.reload(wait_until="domcontentloaded", timeout=120_000)
            second_ready, refresh_detail = wait_for_page_ready(page, "新闻事件")
            route_kept = page.url.rstrip("/").endswith("/news") and first_ready and second_ready
            record(results, "页面刷新保持业务路由", route_kept, f"url={page.url}; {refresh_detail}")

            forbidden_buttons = ["保存默认方案", "运行回测", "保存监控快照", "保存设置", "确认执行"]
            readonly_cases = [
                ("/models/search", "模型搜索与回测"),
                ("/backtests", "回测分析"),
                ("/settings", "系统设置"),
                ("/monitor", "系统监控"),
            ]
            found: list[str] = []
            readiness_failures: list[str] = []
            for route, heading in readonly_cases:
                page.goto(f"{args.url}{route}", wait_until="domcontentloaded", timeout=120_000)
                ready, detail = wait_for_page_ready(page, heading)
                if not ready:
                    readiness_failures.append(f"{route}:{detail}")
                    continue
                for label in forbidden_buttons:
                    if page.get_by_role("button", name=label, exact=False).count():
                        found.append(f"{route}:{label}")
            record(
                results,
                "只读页面无写操作按钮",
                not found and not readiness_failures,
                f"buttons={found}; readiness_failures={readiness_failures}",
            )
        except Exception as exc:
            record(results, "React Chrome 执行", False, f"{type(exc).__name__}: {exc}")
            try:
                screenshot(page, screenshots, "99_failure")
            except Exception:
                pass
        finally:
            browser.close()

    meaningful_errors = [item for item in console_errors if "favicon" not in item.lower()]
    record(results, "React 控制台无未捕获错误", not meaningful_errors, " | ".join(meaningful_errors[-15:]))

    passed = sum(1 for item in results if item["success"])
    failed = len(results) - passed
    report = {"stage": "6.2", "passed": passed, "failed": failed, "results": results}
    (output / "browser_test_result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Stage 6.2 Read-only Page Acceptance", "", f"- Passed: {passed}", f"- Failed: {failed}", ""]
    lines.extend(f"- [{'PASS' if item['success'] else 'FAIL'}] {item['name']} — {item['detail']}" for item in results)
    (output / "acceptance_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
