from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from playwright.sync_api import Page, sync_playwright


def record(results: list[dict[str, Any]], name: str, success: bool, detail: str = "") -> None:
    results.append({"name": name, "success": bool(success), "detail": str(detail)})


def format_console_message(item: Any) -> str:
    """Serialize browser console errors without collapsing object arguments to 'Object'."""
    values: list[Any] = []
    for arg in getattr(item, "args", []) or []:
        try:
            values.append(arg.json_value())
        except Exception:
            values.append(str(arg))
    location = getattr(item, "location", None) or {}
    suffix = ""
    if isinstance(location, dict) and location.get("url"):
        suffix = f" @ {location.get('url')}:{location.get('lineNumber', 0)}:{location.get('columnNumber', 0)}"
    if values:
        try:
            return json.dumps(values, ensure_ascii=False, default=str) + suffix
        except Exception:
            return str(values) + suffix
    return str(getattr(item, "text", item)) + suffix


def envelope(api_url: str, path: str, *, method: str = "get", body: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any], str]:
    try:
        response = requests.request(method, f"{api_url}{path}", json=body, timeout=120)
        payload = response.json()
        return response.status_code == 200 and isinstance(payload, dict), payload, f"status={response.status_code}; success={payload.get('success')}"
    except Exception as exc:
        return False, {}, f"{type(exc).__name__}: {exc}"


def wait_page(page: Page, heading: str, timeout: int = 180_000) -> tuple[bool, str]:
    try:
        page.get_by_role("heading", name=heading, exact=True).first.wait_for(state="visible", timeout=timeout)
        loading = page.locator(".page-loading")
        if loading.count():
            loading.first.wait_for(state="hidden", timeout=timeout)
        page.wait_for_timeout(800)
        body = page.locator("body").inner_text()
        markers = ["页面渲染失败", "AI 模拟盘加载失败", "Request failed with status code", "Cannot read properties"]
        hits = [item for item in markers if item in body]
        return not hits, f"heading={heading}; marker_hits={hits}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def poll_task(api_url: str, task_id: str, timeout: int = 120) -> dict[str, Any]:
    deadline = time.time() + timeout
    last: dict[str, Any] = {}
    while time.time() < deadline:
        ok, payload, _ = envelope(api_url, f"/api/v1/tasks/{task_id}")
        if ok and payload.get("success") is True:
            last = payload.get("data") or {}
            if str(last.get("status")) in {"succeeded", "failed", "cancelled", "timed_out", "interrupted"}:
                return last
        time.sleep(0.5)
    return last



def dismiss_confirm_modal(page: Any, modal: Any) -> tuple[bool, str]:
    """Dismiss an Ant Design Modal.confirm without triggering its primary action."""
    try:
        labels = [
            value.strip()
            for value in modal.locator(".ant-modal-confirm-btns button").all_inner_texts()
            if value.strip()
        ]
    except Exception:
        labels = []

    candidates = [
        modal.locator(".ant-modal-confirm-btns .ant-btn-default"),
        modal.locator(".ant-modal-confirm-btns button").filter(
            has_text=re.compile(r"取\s*消")
        ),
    ]
    for candidate in candidates:
        try:
            if candidate.count():
                candidate.first.click(timeout=10_000, force=True)
                page.wait_for_timeout(350)
                if page.locator(".ant-modal-wrap:visible").count() == 0:
                    return True, f"dismissed by cancel control; buttons={labels}"
        except Exception:
            continue

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(350)
        if page.locator(".ant-modal-wrap:visible").count() == 0:
            return True, f"dismissed by Escape; buttons={labels}"
    except Exception:
        pass

    return False, f"modal remains visible; buttons={labels}"


def clear_visible_confirm_modals(page: Any) -> tuple[bool, str]:
    details: list[str] = []
    for _ in range(3):
        visible = page.locator(".ant-modal:visible")
        if visible.count() == 0:
            return True, "; ".join(details) or "no visible modal"
        dismissed, detail = dismiss_confirm_modal(page, visible.first)
        details.append(detail)
        if not dismissed:
            break
    return page.locator(".ant-modal-wrap:visible").count() == 0, "; ".join(details)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:3000")
    parser.add_argument("--api-url", default="http://127.0.0.1:8010")
    parser.add_argument("--streamlit-url", default="http://127.0.0.1:8501")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    output = Path(args.output_dir)
    shots = output / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    ok, payload, detail = envelope(args.api_url, "/api/v1/health")
    record(results, "FastAPI health", ok and payload.get("success") is True, detail)

    ok, settings_payload, settings_detail = envelope(args.api_url, "/api/v1/web/settings")
    system_user_id = str(((settings_payload.get("data") or {}).get("current_user_id") or "default")).strip() or "default"
    record(
        results,
        "System current user is available",
        ok and settings_payload.get("success") is True and bool(system_user_id),
        f"user_id={system_user_id}; {settings_detail}",
    )
    try:
        response = requests.get(f"{args.streamlit_url}/_stcore/health", timeout=20)
        record(results, "Streamlit baseline retained", response.status_code == 200, f"status={response.status_code}")
    except Exception as exc:
        record(results, "Streamlit baseline retained", False, str(exc))

    try:
        openapi = requests.get(f"{args.api_url}/openapi.json", timeout=30).json()
        paths = openapi.get("paths") or {}
        paper = {key: value for key, value in paths.items() if key.startswith("/api/v1/web/paper-trading")}
        methods = {key: sorted(method for method in value if method != "parameters") for key, value in paper.items()}
        record(results, "Paper trading REST contract", len(paper) >= 13 and any("post" in value for value in methods.values()) and any("put" in value for value in methods.values()), f"paths={len(paper)}; methods={methods}")
    except Exception as exc:
        record(results, "Paper trading REST contract", False, str(exc))

    encoded_user_id = quote(system_user_id, safe="")
    for name, path in [
        ("Paper summary", f"/api/v1/web/paper-trading/summary?user_id={encoded_user_id}"),
        ("Paper profile", f"/api/v1/web/paper-trading/profile?user_id={encoded_user_id}"),
        ("Paper proposals", f"/api/v1/web/paper-trading/proposals?user_id={encoded_user_id}"),
    ]:
        ok, payload, detail = envelope(args.api_url, path)
        data = payload.get("data") or {}
        user_matches = name == "Paper proposals" or str(data.get("user_id") or system_user_id) == system_user_id
        record(results, name, ok and payload.get("success") is True and user_matches, f"user_id={system_user_id}; {detail}")

    rejected_body = {
        "request_id": "stage63-rejected-profile",
        "idempotency_key": "stage63-rejected-profile",
        "user_id": "stage63_acceptance",
        "profile": {"available_capital": 10000},
        "confirmed": False,
    }
    ok, payload, detail = envelope(args.api_url, "/api/v1/web/paper-trading/profile", method="put", body=rejected_body)
    error_text = json.dumps(payload, ensure_ascii=False)
    record(results, "Unconfirmed profile write is rejected", ok and payload.get("success") is False and "confirmation_required" in error_text and "token" not in error_text.lower(), detail)


    ok, ranking_payload, ranking_detail = envelope(args.api_url, "/api/v1/web/dashboard/rankings?offset=0&limit=5")
    ranking_records = (ranking_payload.get("data") or {}).get("records") or []
    score_values = [record.get("pred_score") for record in ranking_records if isinstance(record, dict)]
    record(
        results,
        "Ranking API exposes model score",
        ok and ranking_payload.get("success") is True and bool(ranking_records) and any(value is not None for value in score_values),
        f"scores={score_values}; {ranking_detail}",
    )

    commit_body = {
        "request_id": "stage63-missing-plan",
        "idempotency_key": "stage63-missing-plan",
        "user_id": "stage63_acceptance",
        "confirmation_text": "CONFIRM-000000",
    }
    ok, payload, detail = envelope(args.api_url, "/api/v1/web/paper-trading/proposals/missing-plan/commit", method="post", body=commit_body)
    record(results, "Unknown proposal cannot write", ok and payload.get("success") is False, detail)

    task_body = {
        "task_type": "paper-profile.ai-news-adjustment",
        "args": [],
        "kwargs": {"user_id": "stage63_acceptance", "top_k": 1, "paper_trading_enabled": False, "dry_run": True},
        "owner_id": "stage63_acceptance",
        "session_id": "stage63-browser-acceptance",
        "metadata": {"surface": "stage6.3-acceptance"},
        "timeout_seconds": 120,
        "max_retries": 0,
    }
    ok, payload, detail = envelope(args.api_url, "/api/v1/tasks", method="post", body=task_body)
    task_id = str((payload.get("data") or {}).get("task_id") or "")
    record(results, "Paper task submission returns task_id", ok and payload.get("success") is True and bool(task_id), detail)
    if task_id:
        task = poll_task(args.api_url, task_id)
        record(results, "Paper task reaches terminal state", task.get("status") == "succeeded", f"task_id={task_id}; status={task.get('status')}; message={task.get('message')}")
        ok, list_payload, list_detail = envelope(args.api_url, "/api/v1/tasks?owner_id=stage63_acceptance&session_id=stage63-browser-acceptance&limit=10")
        listed = any(str(item.get("task_id")) == task_id for item in (list_payload.get("data") or []))
        record(results, "Task can be recovered by owner and session", ok and listed, list_detail)
        ok, ack_payload, ack_detail = envelope(args.api_url, f"/api/v1/tasks/{task_id}/acknowledge", method="post")
        record(results, "Terminal task acknowledge", ok and ack_payload.get("success") is True, ack_detail)

    console_errors: list[str] = []
    browser_runtime_errors: list[str] = []

    def record_browser_exception(name: str, exc: BaseException) -> None:
        detail = f"{type(exc).__name__}: {exc}"
        browser_runtime_errors.append(f"{name}: {detail}")
        record(results, name, False, detail)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=not args.headed)
            page = browser.new_page(viewport={"width": 1680, "height": 1050})
            page.set_default_timeout(90_000)
            page.on("console", lambda item: console_errors.append(format_console_message(item)) if item.type == "error" else None)
            page.on("pageerror", lambda error: console_errors.append(str(error)))
            try:
                # 1. Paper-trading page core rendering and UI layout.
                try:
                    page.goto(f"{args.url}/paper-trading", wait_until="domcontentloaded", timeout=120_000)
                    ready, ready_detail = wait_page(page, "AI 模拟盘")
                    body = page.locator("body").inner_text()
                    required_sections = [
                        "账户摘要",
                        "长任务与恢复",
                        "用户画像与模拟资金",
                        "账户资产走势",
                        "资金管理",
                        "历史模拟盘回填",
                        "待确认预案",
                    ]
                    missing = [item for item in required_sections if item not in body]
                    record(
                        results,
                        "React AI paper trading page renders",
                        ready and not missing,
                        f"{ready_detail}; missing={missing}",
                    )
                except Exception as exc:
                    record_browser_exception("React AI paper trading page renders", exc)

                try:
                    collapse_all = page.get_by_role("button", name="全部收起", exact=True)
                    expand_all = page.get_by_role("button", name="全部展开", exact=True)
                    controls_ok = collapse_all.count() == 1 and expand_all.count() == 1
                    collapsed_sections = 0
                    if controls_ok:
                        collapse_all.click(timeout=20_000)
                        page.wait_for_timeout(400)
                        collapsed_sections = page.get_by_role("button", name="展开", exact=True).count()
                        expand_all.click(timeout=20_000)
                        page.wait_for_timeout(400)
                    record(
                        results,
                        "Paper sections support collapse and expand",
                        controls_ok and collapsed_sections >= 7,
                        f"controls={controls_ok}; collapsed_sections={collapsed_sections}",
                    )
                except Exception as exc:
                    record_browser_exception("Paper sections support collapse and expand", exc)

                try:
                    scroll_state = page.evaluate(
                        """() => {
                          const sidebar = document.querySelector('.app-sider-menu-scroll');
                          const content = document.querySelector('.app-content-scroll');
                          return {
                            htmlOverflow: getComputedStyle(document.documentElement).overflow,
                            bodyOverflow: getComputedStyle(document.body).overflow,
                            sidebarOverflowY: sidebar ? getComputedStyle(sidebar).overflowY : null,
                            contentOverflowY: content ? getComputedStyle(content).overflowY : null,
                            sidebarScrollable: sidebar ? sidebar.scrollHeight >= sidebar.clientHeight : false,
                            contentScrollable: content ? content.scrollHeight > content.clientHeight : false,
                          };
                        }"""
                    )
                    independent_scroll = (
                        scroll_state.get("htmlOverflow") == "hidden"
                        and scroll_state.get("bodyOverflow") == "hidden"
                        and scroll_state.get("sidebarOverflowY") == "auto"
                        and scroll_state.get("contentOverflowY") == "auto"
                        and scroll_state.get("contentScrollable") is True
                    )
                    record(
                        results,
                        "Sidebar and content use independent scroll containers",
                        independent_scroll,
                        json.dumps(scroll_state, ensure_ascii=False),
                    )
                except Exception as exc:
                    record_browser_exception("Sidebar and content use independent scroll containers", exc)

                try:
                    user_context = page.get_by_test_id("paper-user-context")
                    context_text = user_context.inner_text() if user_context.count() else ""
                    record(
                        results,
                        "React uses the system current user instead of the legacy test account",
                        bool(context_text)
                        and system_user_id in context_text
                        and "refactor_test" not in context_text.split("旧版验收账号", 1)[0],
                        f"system_user_id={system_user_id}; context={context_text[:300]}",
                    )
                except Exception as exc:
                    record_browser_exception(
                        "React uses the system current user instead of the legacy test account",
                        exc,
                    )

                try:
                    page.screenshot(path=str(shots / "01_paper_trading.png"), full_page=True)
                except Exception as exc:
                    record_browser_exception("Paper page screenshot", exc)

                # 2. Protected browser actions. Every check is isolated so one locator
                # failure cannot prevent refresh, dashboard, or report generation.
                try:
                    buttons = [
                        "更新 AI 模拟盘",
                        "运行新闻调整",
                        "手动运行调度器",
                        "保存画像",
                        "生成预案",
                        "生成回填预案",
                    ]
                    missing_buttons = [
                        name
                        for name in buttons
                        if page.get_by_role("button", name=name, exact=True).count() == 0
                    ]
                    record(
                        results,
                        "Paper actions are exposed through protected controls",
                        not missing_buttons,
                        f"missing={missing_buttons}",
                    )
                except Exception as exc:
                    record_browser_exception(
                        "Paper actions are exposed through protected controls",
                        exc,
                    )

                try:
                    profile_button = page.get_by_role("button", name="保存画像", exact=True)
                    if profile_button.count() != 1:
                        record(
                            results,
                            "Profile update is protected in the browser",
                            False,
                            f"save_button_count={profile_button.count()}",
                        )
                    else:
                        profile_button.scroll_into_view_if_needed(timeout=20_000)
                        profile_button.click(timeout=20_000)
                        page.wait_for_timeout(900)

                        visible_modal = page.locator(".ant-modal:visible").filter(
                            has_text="确认更新模拟盘用户画像？"
                        )
                        if visible_modal.count():
                            modal = visible_modal.first
                            try:
                                page.screenshot(
                                    path=str(shots / "04_profile_confirmation.png"),
                                    full_page=True,
                                )
                            except Exception:
                                pass
                            dismissed, dismiss_detail = dismiss_confirm_modal(
                                page, modal
                            )
                            record(
                                results,
                                "Profile update is protected in the browser",
                                dismissed,
                                f"second-confirmation modal shown; {dismiss_detail}",
                            )
                            if not dismissed:
                                page.reload(
                                    wait_until="domcontentloaded",
                                    timeout=120_000,
                                )
                                wait_page(page, "AI 模拟盘")
                        else:
                            validation_errors = page.locator(
                                ".ant-form-item-has-error"
                            ).count()
                            record(
                                results,
                                "Profile update is protected in the browser",
                                validation_errors > 0,
                                f"form blocked before write; validation_errors={validation_errors}",
                            )
                except Exception as exc:
                    record_browser_exception(
                        "Profile update is protected in the browser",
                        exc,
                    )

                try:
                    cleared, clear_detail = clear_visible_confirm_modals(page)
                    if not cleared:
                        page.reload(
                            wait_until="domcontentloaded",
                            timeout=120_000,
                        )
                        wait_page(page, "AI 模拟盘")
                        cleared, clear_detail = clear_visible_confirm_modals(page)

                    news_button = page.get_by_role(
                        "button", name="运行新闻调整", exact=True
                    )
                    if news_button.count() != 1:
                        record(
                            results,
                            "Long task requires confirmation or profile guard",
                            False,
                            f"news_button_count={news_button.count()}",
                        )
                    elif news_button.is_disabled():
                        guarded = (
                            "请先补全用户画像和模拟资金"
                            in page.locator("body").inner_text()
                        )
                        record(
                            results,
                            "Long task requires confirmation or profile guard",
                            guarded,
                            "button disabled until profile is complete",
                        )
                    else:
                        news_button.scroll_into_view_if_needed(timeout=20_000)
                        news_button.click(timeout=20_000)
                        page.wait_for_timeout(700)
                        visible_modal = page.locator(".ant-modal:visible").filter(
                            has_text="确认运行新闻调整？"
                        )
                        if visible_modal.count():
                            modal = visible_modal.first
                            try:
                                page.screenshot(
                                    path=str(shots / "05_news_task_confirmation.png"),
                                    full_page=True,
                                )
                            except Exception:
                                pass
                            dismissed, dismiss_detail = dismiss_confirm_modal(
                                page, modal
                            )
                            record(
                                results,
                                "Long task requires confirmation or profile guard",
                                dismissed,
                                (
                                    "confirmation modal shown; "
                                    f"precheck={clear_detail}; {dismiss_detail}"
                                ),
                            )
                        else:
                            record(
                                results,
                                "Long task requires confirmation or profile guard",
                                False,
                                (
                                    "enabled task button did not show a confirmation "
                                    f"modal; precheck={clear_detail}"
                                ),
                            )
                except Exception as exc:
                    record_browser_exception(
                        "Long task requires confirmation or profile guard",
                        exc,
                    )

                try:
                    local_storage = page.evaluate(
                        "Object.fromEntries(Object.entries(localStorage))"
                    )
                    serialized = json.dumps(
                        local_storage, ensure_ascii=False
                    ).lower()
                    forbidden_storage = [
                        item
                        for item in [
                            "available_capital",
                            "positions",
                            "cash_flows",
                            "confirmation_token",
                            '"result"',
                            '"events"',
                        ]
                        if item in serialized
                    ]
                    record(
                        results,
                        "localStorage contains recovery metadata only",
                        not forbidden_storage,
                        f"keys={sorted(local_storage)}; forbidden={forbidden_storage}",
                    )
                except Exception as exc:
                    record_browser_exception(
                        "localStorage contains recovery metadata only",
                        exc,
                    )

                # 3. Refresh recovery. This check still runs if a protected-action
                # locator failed above.
                try:
                    page.reload(wait_until="domcontentloaded", timeout=120_000)
                    refreshed, refresh_detail = wait_page(page, "AI 模拟盘")
                    record(
                        results,
                        "Paper route survives refresh",
                        refreshed
                        and page.url.rstrip("/").endswith("/paper-trading"),
                        f"url={page.url}; {refresh_detail}",
                    )
                    page.screenshot(
                        path=str(shots / "02_paper_trading_refresh.png"),
                        full_page=True,
                    )
                except Exception as exc:
                    record_browser_exception("Paper route survives refresh", exc)

                try:
                    text = page.locator("body").inner_text().lower()
                    sensitive = [
                        item
                        for item in [
                            "confirmation_token",
                            "tushare_token",
                            "neo4j_password",
                            "d:\\stock_daily_app",
                            "agent_quant.db",
                        ]
                        if item in text
                    ]
                    record(
                        results,
                        "Paper page does not expose secrets or server paths",
                        not sensitive,
                        f"found={sensitive}",
                    )
                except Exception as exc:
                    record_browser_exception(
                        "Paper page does not expose secrets or server paths",
                        exc,
                    )

                # 4. Dashboard model score. Always attempt this independently.
                try:
                    page.goto(
                        f"{args.url}/dashboard",
                        wait_until="domcontentloaded",
                        timeout=120_000,
                    )
                    dashboard_ready, dashboard_detail = wait_page(
                        page, "首页 / 预测排名"
                    )
                    first_model_score = ""
                    rows = page.locator(".ant-table-tbody > tr.ant-table-row")
                    if rows.count():
                        cells = rows.first.locator("td")
                        if cells.count() >= 4:
                            first_model_score = cells.nth(3).inner_text().strip()
                    record(
                        results,
                        "Dashboard displays model score",
                        dashboard_ready
                        and bool(first_model_score)
                        and first_model_score != "—",
                        f"{dashboard_detail}; first_model_score={first_model_score!r}",
                    )
                    page.screenshot(
                        path=str(shots / "03_dashboard_model_score.png"),
                        full_page=True,
                    )
                except Exception as exc:
                    record_browser_exception(
                        "Dashboard displays model score",
                        exc,
                    )
            finally:
                browser.close()
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        browser_runtime_errors.append(detail)
        record(results, "Browser acceptance runtime", False, detail)
        (output / "browser_acceptance_error.txt").write_text(
            detail + "\n",
            encoding="utf-8",
        )

    record(
        results,
        "Browser console has no uncaught errors",
        not console_errors,
        "; ".join(console_errors[-10:]),
    )
    if browser_runtime_errors:
        (output / "browser_runtime_errors.json").write_text(
            json.dumps(browser_runtime_errors, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    report = {
        "stage": "6.3",
        "passed": sum(1 for item in results if item["success"]),
        "failed": sum(1 for item in results if not item["success"]),
        "results": results,
    }
    (output / "browser_test_result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Stage 6.3 Browser Acceptance", "", f"- Passed: {report['passed']}", f"- Failed: {report['failed']}", ""]
    for item in results:
        lines.append(f"- [{'PASS' if item['success'] else 'FAIL'}] {item['name']}: {item['detail']}")
    (output / "acceptance_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
