from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page, sync_playwright

TOP_LEVEL_EXPECTATIONS = {
    "首页 / 预测排名": "二、预测下一交易日股票排名",
    "AI 模拟盘": "用户与账户摘要",
    "AI Agent": "AI Agent 控制中心",
    "系统监控": "分层指标",
}
HOME_SECTION_EXPECTATIONS = {
    "首页 / 预测排名": "二、预测下一交易日股票排名",
    "个股详情": "五、个股走势查看",
    "模型指标": "一、模型与数据状态",
    "模型搜索与回测": "模型搜索与回测结果",
    "回测分析": "六、基础 T+1 回测分析",
    "新闻事件": "新闻事件",
    "系统设置": "系统设置",
}
FATAL_MARKERS = (
    "Traceback (most recent call last)",
    "ModuleNotFoundError",
    "ImportError:",
    "NameError:",
    "AttributeError:",
    "SyntaxError:",
)
MAIN_SCROLL_SELECTORS = (
    '[data-testid="stMain"]',
    'section.main',
    '[data-testid="stAppViewContainer"]',
)


def record(results: list[dict[str, Any]], name: str, success: bool, detail: str = "") -> None:
    results.append({"name": name, "success": bool(success), "detail": str(detail)})


def screenshot(page: Page, directory: Path, name: str) -> None:
    safe_name = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in name)
    page.screenshot(path=str(directory / f"{safe_name}.png"), full_page=True)


def wait_for_text(page: Page, expected: str, timeout: int = 60_000) -> bool:
    try:
        page.get_by_text(expected, exact=False).first.wait_for(timeout=timeout)
        return True
    except Exception:
        return False


def page_has_fatal_error(page: Page) -> tuple[bool, str]:
    body = page.locator("body").inner_text()
    matches = [marker for marker in FATAL_MARKERS if marker in body]
    return bool(matches), ", ".join(matches)


def scroll_main_to_bottom(page: Page) -> None:
    """Scroll Streamlit's internal main container, not only the browser window."""
    for selector in MAIN_SCROLL_SELECTORS:
        locator = page.locator(selector)
        if not locator.count():
            continue
        try:
            locator.first.evaluate("(el) => { el.scrollTop = el.scrollHeight; }")
        except Exception:
            pass
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    except Exception:
        pass


def locate_radio(page: Page, label: str) -> Locator:
    """Find a radio by exact accessible name, then use a relaxed fallback."""
    exact = page.get_by_role("radio", name=label, exact=True)
    if exact.count():
        return exact
    return page.get_by_role("radio", name=label, exact=False)


def wait_for_radio_count(
    page: Page,
    label: str,
    *,
    minimum_count: int,
    timeout: int = 120_000,
) -> Locator:
    """Wait for Streamlit's incremental/lazy widget rendering to finish."""
    deadline = time.monotonic() + timeout / 1000
    last_count = 0
    while time.monotonic() < deadline:
        fatal, markers = page_has_fatal_error(page)
        if fatal:
            raise RuntimeError(f"页面出现致命错误：{markers}")

        radios = locate_radio(page, label)
        last_count = radios.count()
        if last_count >= minimum_count:
            return radios

        scroll_main_to_bottom(page)
        page.wait_for_timeout(1000)

    raise RuntimeError(
        f"等待单选项超时：{label}，期望至少 {minimum_count} 个，实际数量={last_count}"
    )


def click_radio(
    page: Page,
    label: str,
    *,
    occurrence: int = 0,
    timeout: int = 120_000,
) -> None:
    """Select a Streamlit/React-Aria radio without relying on pointer hit-testing."""
    radios = wait_for_radio_count(
        page,
        label,
        minimum_count=occurrence + 1,
        timeout=timeout,
    )
    target = radios.nth(occurrence)

    # The current item may already be selected. Clicking it again is unnecessary and
    # can be blocked by Streamlit's sticky header or the React-Aria radiogroup layer.
    try:
        if target.is_checked():
            page.wait_for_timeout(300)
            return
    except Exception:
        pass

    try:
        target.scroll_into_view_if_needed(timeout=10_000)
    except Exception:
        pass

    # `force=True` bypasses Streamlit overlay hit-testing while still using the
    # native radio input and dispatching the events expected by React.
    try:
        target.check(force=True, timeout=15_000)
    except Exception:
        # Last-resort DOM click: it does not depend on the pointer-interception layer.
        target.evaluate("(element) => element.click()")

    page.wait_for_timeout(1800)


def wait_for_app_settle(page: Page, *, timeout: int = 120_000) -> None:
    """Use the top-level selector as the completion signal for the Streamlit run."""
    wait_for_radio_count(
        page,
        "首页 / 预测排名",
        minimum_count=1,
        timeout=timeout,
    )


def verify_surface(
    page: Page,
    results: list[dict[str, Any]],
    screenshots: Path,
    *,
    test_name: str,
    expected_text: str,
    screenshot_name: str,
) -> None:
    visible = wait_for_text(page, expected_text, timeout=120_000)
    fatal, markers = page_has_fatal_error(page)
    success = visible and not fatal
    detail = f"expected={expected_text}"
    if fatal:
        detail += f"; fatal={markers}"
    record(results, test_name, success, detail)
    screenshot(page, screenshots, screenshot_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8512")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--deep-agent-check", action="store_true")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    screenshots = output_dir / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    started = datetime.now().isoformat(timespec="seconds")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=not args.headed)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.set_default_timeout(60_000)
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=90_000)
            app_open = wait_for_text(page, "A股每日股票评分系统", timeout=90_000)
            fatal, markers = page_has_fatal_error(page)
            record(
                results,
                "应用首页可打开",
                app_open and not fatal,
                f"fatal={markers}" if fatal else "Streamlit 页面已加载",
            )
            screenshot(page, screenshots, "01_home")

            # Dedicated test user. The script deliberately does not click “保存用户 ID”.
            user_input = page.get_by_label("当前用户 ID", exact=True)
            if user_input.count():
                user_input.fill("refactor_test")
                user_input.press("Enter")
                page.wait_for_timeout(1200)
                record(results, "测试用户可输入", user_input.input_value() == "refactor_test")
            else:
                record(results, "测试用户可输入", False, "未找到当前用户 ID 输入框")

            wait_for_app_settle(page, timeout=120_000)
            record(results, "Streamlit 主脚本完成渲染", True, "已找到顶层页面选择器")

            for index, (label, expected) in enumerate(TOP_LEVEL_EXPECTATIONS.items(), start=2):
                click_radio(page, label, occurrence=0)
                verify_surface(
                    page,
                    results,
                    screenshots,
                    test_name=f"顶层页面：{label}",
                    expected_text=expected,
                    screenshot_name=f"{index:02d}_top_{label}",
                )

            # Return to home. When home is rendered, the same label occurs twice:
            # occurrence 0 is the top-level selector and occurrence 1 is the home module selector.
            click_radio(page, "首页 / 预测排名", occurrence=0)
            wait_for_text(page, TOP_LEVEL_EXPECTATIONS["首页 / 预测排名"], timeout=120_000)
            for index, (label, expected) in enumerate(HOME_SECTION_EXPECTATIONS.items(), start=10):
                occurrence = 1 if label == "首页 / 预测排名" else 0
                click_radio(page, label, occurrence=occurrence)
                verify_surface(
                    page,
                    results,
                    screenshots,
                    test_name=f"首页模块：{label}",
                    expected_text=expected,
                    screenshot_name=f"{index:02d}_home_section_{label}",
                )

            all_radio_text = page.get_by_role("radio").all_inner_texts()
            obsolete = [item for item in ("RAG 检索", "AI 解释") if item in all_radio_text]
            record(
                results,
                "废弃独立模块已删除",
                not obsolete,
                f"仍存在：{obsolete}" if obsolete else "RAG 检索/AI 解释不再是独立模块",
            )

            if args.deep_agent_check:
                click_radio(page, "AI Agent", occurrence=0)
                wait_for_text(page, "AI Agent 控制中心", timeout=120_000)
                chat = page.locator(
                    'textarea[aria-label="Chat input"], textarea[data-testid="stChatInputTextArea"]'
                )
                if chat.count():
                    chat.first.fill("查看当前模拟盘账户和持仓")
                    chat.first.press("Enter")
                    before = time.time()
                    success = False
                    while time.time() - before < 180:
                        text = page.locator("body").inner_text()
                        fatal, _ = page_has_fatal_error(page)
                        if not fatal and "不构成投资建议" in text and ("持仓" in text or "账户" in text):
                            success = True
                            break
                        page.wait_for_timeout(1500)
                    record(
                        results,
                        "AI Agent 只读查询",
                        success,
                        "使用 refactor_test，查询账户和持仓，不执行写操作",
                    )
                    screenshot(page, screenshots, "30_agent_read_only_query")
                else:
                    record(results, "AI Agent 只读查询", False, "未找到聊天输入框")
        except Exception as exc:
            record(results, "浏览器执行异常", False, f"{type(exc).__name__}: {exc}")
            try:
                screenshot(page, screenshots, "99_failure")
            except Exception:
                pass
        finally:
            browser.close()

    passed = sum(1 for item in results if item["success"])
    failed = len(results) - passed
    payload = {
        "stage": 2,
        "started_at": started,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "url": args.url,
        "passed": passed,
        "failed": failed,
        "results": results,
    }
    (output_dir / "browser_test_result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Stage 2 Browser Acceptance",
        "",
        f"- Passed: {passed}",
        f"- Failed: {failed}",
        "",
    ]
    for item in results:
        mark = "PASS" if item["success"] else "FAIL"
        lines.append(f"- [{mark}] {item['name']} — {item['detail']}")
    (output_dir / "acceptance_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
