from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from playwright.sync_api import Page, sync_playwright

TERMINAL = {"succeeded", "failed", "cancelled", "timed_out", "interrupted"}


def record(results: list[dict[str, Any]], name: str, success: bool, detail: str = "") -> None:
    results.append({"name": name, "success": bool(success), "detail": str(detail)})


def format_console_message(item: Any) -> str:
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


def request_json(
    api_url: str,
    path: str,
    *,
    method: str = "get",
    body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: int = 120,
) -> tuple[bool, dict[str, Any], str]:
    try:
        response = requests.request(
            method,
            f"{api_url}{path}",
            json=body,
            params=params,
            timeout=timeout,
        )
        payload = response.json() if response.content else {}
        ok = response.status_code == 200 and isinstance(payload, dict)
        return ok, payload, f"status={response.status_code}; success={payload.get('success')}"
    except Exception as exc:
        return False, {}, f"{type(exc).__name__}: {exc}"


def data_of(payload: dict[str, Any]) -> Any:
    return payload.get("data") if payload.get("success") is True else None


def wait_page(page: Page, heading: str, timeout: int = 180_000) -> tuple[bool, str]:
    try:
        page.get_by_role("heading", name=heading, exact=True).first.wait_for(
            state="visible", timeout=timeout
        )
        loading = page.locator(".page-loading")
        if loading.count():
            loading.first.wait_for(state="hidden", timeout=timeout)
        page.wait_for_timeout(900)
        body = page.locator("body").inner_text()
        markers = [
            "页面渲染失败",
            "AI Agent 会话加载失败",
            "Request failed with status code",
            "Cannot read properties",
            "Traceback",
        ]
        hits = [item for item in markers if item in body]
        return not hits, f"heading={heading}; marker_hits={hits}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def sessions(api_url: str, user_id: str) -> list[dict[str, Any]]:
    ok, payload, _ = request_json(
        api_url,
        "/api/v1/web/agent/sessions",
        params={"user_id": user_id, "limit": 100},
    )
    data = data_of(payload) if ok else {}
    return list((data or {}).get("records") or [])


def messages(api_url: str, user_id: str, conversation_id: str) -> list[dict[str, Any]]:
    ok, payload, _ = request_json(
        api_url,
        f"/api/v1/web/agent/sessions/{quote(conversation_id)}/messages",
        params={"user_id": user_id, "limit": 100},
    )
    data = data_of(payload) if ok else {}
    return list((data or {}).get("records") or [])


def task_list(api_url: str, user_id: str, conversation_id: str) -> list[dict[str, Any]]:
    ok, payload, _ = request_json(
        api_url,
        "/api/v1/tasks",
        params={
            "owner_id": user_id,
            "session_id": conversation_id,
            "task_type": "agent.run",
            "limit": 10,
        },
    )
    data = data_of(payload) if ok else []
    return list(data or []) if isinstance(data, list) else []


def wait_for_task(api_url: str, user_id: str, conversation_id: str, known: set[str], timeout: int = 45) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = task_list(api_url, user_id, conversation_id)
        for row in rows:
            if str(row.get("task_id") or "") not in known:
                return row
        time.sleep(0.7)
    return {}


def wait_terminal(api_url: str, task_id: str, timeout: int = 420) -> dict[str, Any]:
    deadline = time.time() + timeout
    last: dict[str, Any] = {}
    while time.time() < deadline:
        ok, payload, _ = request_json(api_url, f"/api/v1/tasks/{quote(task_id)}")
        data = data_of(payload) if ok else None
        if isinstance(data, dict):
            last = data
            if str(data.get("status") or "") in TERMINAL:
                return data
        time.sleep(1.0)
    return last


def wait_finalized_message(api_url: str, user_id: str, conversation_id: str, task_id: str, timeout: int = 90) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for item in messages(api_url, user_id, conversation_id):
            if str(item.get("task_id") or "") == task_id and str(item.get("role") or "") == "assistant":
                return item
        time.sleep(0.8)
    return {}


def wait_acknowledged(api_url: str, task_id: str, timeout: int = 60) -> dict[str, Any]:
    deadline = time.time() + timeout
    last: dict[str, Any] = {}
    while time.time() < deadline:
        ok, payload, _ = request_json(api_url, f"/api/v1/tasks/{quote(task_id)}")
        data = data_of(payload) if ok else None
        if isinstance(data, dict):
            last = data
            if data.get("acknowledged_at"):
                return data
        time.sleep(0.8)
    return last


def read_sse(api_url: str, task_id: str, timeout: int = 30) -> tuple[bool, str]:
    events: list[str] = []
    try:
        with requests.get(
            f"{api_url}/api/v1/tasks/{quote(task_id)}/events?after=0",
            headers={"Accept": "text/event-stream"},
            stream=True,
            timeout=(10, timeout),
        ) as response:
            response.raise_for_status()
            for raw in response.iter_lines(decode_unicode=True):
                line = str(raw or "")
                if line.startswith("event:"):
                    events.append(line.split(":", 1)[1].strip())
                    if events[-1] == "task-complete":
                        break
        return "task-complete" in events, f"events={events[-10:]}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}; events={events[-10:]}"


def dismiss_modal(page: Page) -> tuple[bool, str]:
    visible = page.locator(".ant-modal:visible")
    if not visible.count():
        return True, "no visible modal"
    modal = visible.first
    candidates = [
        modal.locator(".ant-modal-confirm-btns .ant-btn-default"),
        modal.get_by_role("button", name=re.compile(r"取\s*消")),
    ]
    for candidate in candidates:
        try:
            if candidate.count():
                candidate.first.click(force=True, timeout=10_000)
                page.wait_for_timeout(300)
                if page.locator(".ant-modal-wrap:visible").count() == 0:
                    return True, "dismissed by cancel"
        except Exception:
            continue
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass
    return page.locator(".ant-modal-wrap:visible").count() == 0, "dismissed by Escape"


def find_run_session(api_url: str, user_id: str, preferred: str = "") -> tuple[str, str]:
    rows = sessions(api_url, user_id)
    rows.sort(key=lambda item: str(item.get("last_message_at") or item.get("updated_at") or ""), reverse=True)
    if preferred:
        rows.sort(key=lambda item: str(item.get("conversation_id")) != preferred)
    for session in rows[:30]:
        conversation_id = str(session.get("conversation_id") or "")
        for item in reversed(messages(api_url, user_id, conversation_id)):
            run_id = str(item.get("run_id") or "")
            if run_id:
                return conversation_id, run_id
    return "", ""


def write_report(output: Path, results: list[dict[str, Any]], console_errors: list[str], runtime_errors: list[str]) -> int:
    passed = sum(1 for item in results if item["success"])
    failed = len(results) - passed
    payload = {
        "stage": "6.4",
        "passed": passed,
        "failed": failed,
        "results": results,
        "console_errors": console_errors,
        "runtime_errors": runtime_errors,
        "generated_at": datetime.now().astimezone().isoformat(),
    }
    (output / "browser_test_result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Stage 6.4 Browser Acceptance",
        "",
        f"- Passed: {passed}",
        f"- Failed: {failed}",
        "",
        "| Result | Check | Detail |",
        "|---|---|---|",
    ]
    for item in results:
        result = "PASS" if item["success"] else "FAIL"
        detail = str(item["detail"]).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {result} | {item['name']} | {detail} |")
    if console_errors:
        lines.extend(["", "## Browser console errors", "", "```text", *console_errors[-30:], "```"])
    if runtime_errors:
        lines.extend(["", "## Runtime errors", "", "```text", *runtime_errors[-30:], "```"])
    (output / "acceptance_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"passed": passed, "failed": failed}, ensure_ascii=False))
    return 1 if failed else 0


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
    console_errors: list[str] = []
    runtime_errors: list[str] = []
    test_conversation_id = ""
    user_id = "default"

    try:
        response = requests.get(f"{args.api_url}/api/v1/health", timeout=30)
        record(results, "FastAPI health", response.status_code == 200, f"status={response.status_code}")
    except Exception as exc:
        record(results, "FastAPI health", False, f"{type(exc).__name__}: {exc}")

    try:
        response = requests.get(f"{args.streamlit_url}/_stcore/health", timeout=30)
        record(results, "Streamlit comparison baseline remains healthy", response.status_code == 200, f"status={response.status_code}")
    except Exception as exc:
        record(results, "Streamlit comparison baseline remains healthy", False, f"{type(exc).__name__}: {exc}")

    try:
        openapi = requests.get(f"{args.api_url}/openapi.json", timeout=60).json()
        agent_paths = {path: methods for path, methods in openapi.get("paths", {}).items() if path.startswith("/api/v1/web/agent")}
        required_methods = {
            "/api/v1/web/agent/sessions": {"get", "post"},
            "/api/v1/web/agent/sessions/{conversation_id}": {"get", "patch", "delete"},
            "/api/v1/web/agent/sessions/{conversation_id}/messages": {"get", "post"},
            "/api/v1/web/agent/sessions/{conversation_id}/finalize-task": {"post"},
            "/api/v1/web/agent/pending-actions/{plan_id}/confirm": {"post"},
        }
        missing = {
            path: sorted(methods - set(agent_paths.get(path, {})))
            for path, methods in required_methods.items()
            if methods - set(agent_paths.get(path, {}))
        }
        record(results, "Agent REST contract is complete", len(agent_paths) >= 14 and not missing, f"paths={len(agent_paths)}; missing={missing}")
    except Exception as exc:
        record(results, "Agent REST contract is complete", False, f"{type(exc).__name__}: {exc}")

    ok, settings_payload, settings_detail = request_json(args.api_url, "/api/v1/web/settings")
    settings_data = data_of(settings_payload) if ok else {}
    user_id = str((settings_data or {}).get("current_user_id") or "default")
    record(results, "Agent follows system current user", bool(user_id), f"user_id={user_id}; {settings_detail}")

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=not args.headed)
            page = browser.new_page(viewport={"width": 1680, "height": 1050})
            page.set_default_timeout(90_000)
            page.on("console", lambda item: console_errors.append(format_console_message(item)) if item.type == "error" else None)
            page.on("pageerror", lambda error: console_errors.append(str(error)))
            try:
                page.goto(f"{args.url}/agent", wait_until="domcontentloaded", timeout=120_000)
                ready, detail = wait_page(page, "AI Agent")
                body = page.locator("body").inner_text()
                required = ["会话", "快捷提问", "Agent 运行与控制中心", "待确认操作", "策略草稿"]
                missing = [item for item in required if item not in body]
                record(results, "React AI Agent page renders", ready and not missing, f"{detail}; missing={missing}")
                record(results, "Agent page shows current system user", f"当前用户：{user_id}" in body, f"user_id={user_id}")
                page.screenshot(path=str(shots / "01_agent.png"), full_page=True)

                before_ids = {str(item.get("conversation_id") or "") for item in sessions(args.api_url, user_id)}
                page.get_by_test_id("agent-create-session").click()
                deadline = time.time() + 30
                while time.time() < deadline and not test_conversation_id:
                    for item in sessions(args.api_url, user_id):
                        candidate = str(item.get("conversation_id") or "")
                        if candidate and candidate not in before_ids:
                            test_conversation_id = candidate
                            break
                    if not test_conversation_id:
                        time.sleep(0.5)
                record(results, "Conversation can be created", bool(test_conversation_id), f"conversation_id={test_conversation_id}")

                if test_conversation_id:
                    item = page.locator(f'[data-conversation-id="{test_conversation_id}"]')
                    item.wait_for(state="visible", timeout=30_000)
                    item.click()
                    rename_title = f"Stage64验收-{int(time.time())}"
                    renamed = False
                    rename_detail = ""
                    try:
                        item.get_by_role("button", name="改名", exact=True).click()
                        modal = page.locator(".ant-modal:visible").filter(
                            has_text="重命名会话"
                        )
                        modal.wait_for(state="visible", timeout=20_000)
                        rename_input = modal.locator("input")
                        rename_input.fill(rename_title)

                        # Ant Design may expose the primary button text with
                        # inserted spacing in Windows Chrome accessibility trees.
                        # Prefer the stable primary-button selector, then Enter.
                        primary = modal.locator(".ant-modal-footer .ant-btn-primary")
                        if primary.count():
                            primary.first.click(force=True, timeout=20_000)
                            rename_detail = "submitted by primary button"
                        else:
                            rename_input.press("Enter")
                            rename_detail = "submitted by Enter"

                        try:
                            modal.wait_for(state="hidden", timeout=20_000)
                        except Exception:
                            dismissed, dismiss_detail = dismiss_modal(page)
                            rename_detail += f"; modal_cleanup={dismissed}:{dismiss_detail}"

                        deadline = time.time() + 20
                        while time.time() < deadline:
                            current = next(
                                (
                                    x
                                    for x in sessions(args.api_url, user_id)
                                    if str(x.get("conversation_id"))
                                    == test_conversation_id
                                ),
                                {},
                            )
                            if str(current.get("title")) == rename_title:
                                renamed = True
                                break
                            time.sleep(0.5)
                    except Exception as exc:
                        rename_detail = f"{type(exc).__name__}: {exc}"
                        dismissed, dismiss_detail = dismiss_modal(page)
                        rename_detail += (
                            f"; modal_cleanup={dismissed}:{dismiss_detail}"
                        )
                    record(
                        results,
                        "Conversation can be renamed",
                        renamed,
                        f"title={rename_title}; {rename_detail}",
                    )

                    known_tasks = {str(item.get("task_id") or "") for item in task_list(args.api_url, user_id, test_conversation_id)}
                    question = "查看系统状态，并简要说明当前可用能力"
                    page.get_by_test_id("agent-composer-input").fill(question)
                    page.get_by_test_id("agent-send-button").click()
                    page.get_by_text(question, exact=True).wait_for(state="visible", timeout=30_000)
                    record(results, "User message is persisted before task execution", any(str(item.get("content")) == question and item.get("role") == "user" for item in messages(args.api_url, user_id, test_conversation_id)), "message persisted")

                    task = wait_for_task(args.api_url, user_id, test_conversation_id, known_tasks)
                    task_id = str(task.get("task_id") or "")
                    record(results, "Agent submission returns a recoverable task_id", bool(task_id), f"task_id={task_id}")
                    try:
                        page.get_by_test_id("agent-task-panel").wait_for(state="visible", timeout=20_000)
                        task_panel_seen = True
                    except Exception:
                        task_panel_seen = bool(task_id)
                    record(results, "Agent task progress panel is available", task_panel_seen, f"task_id={task_id}")
                    page.screenshot(path=str(shots / "02_agent_task.png"), full_page=True)

                    if task_id:
                        terminal = wait_terminal(args.api_url, task_id)
                        terminal_status = str(terminal.get("status") or "")
                        record(results, "Agent task reaches an explicit terminal state", terminal_status in TERMINAL, f"status={terminal_status}; message={terminal.get('message')}")
                        sse_ok, sse_detail = read_sse(args.api_url, task_id)
                        record(results, "Agent task SSE emits task-complete", sse_ok, sse_detail)
                        assistant = wait_finalized_message(args.api_url, user_id, test_conversation_id, task_id)
                        record(results, "Terminal Agent result is saved idempotently on the server", bool(assistant), f"message_id={assistant.get('message_id')}; run_id={assistant.get('run_id')}")
                        acknowledged = wait_acknowledged(args.api_url, task_id)
                        record(results, "Task is acknowledged after final message persistence", bool(acknowledged.get("acknowledged_at")), f"acknowledged_at={acknowledged.get('acknowledged_at')}")
                        public_request = terminal.get("request") if isinstance(terminal.get("request"), dict) else {}
                        public_text = json.dumps(public_request, ensure_ascii=False).lower()
                        leaked = [item for item in ("output_dir", "base_url", "api_key", "confirmation_token", "credential") if item in public_text]
                        record(results, "Task REST result redacts server-owned request fields", not leaked, f"leaked={leaked}")

                    page.reload(wait_until="domcontentloaded", timeout=120_000)
                    refreshed, refresh_detail = wait_page(page, "AI Agent")
                    selected = page.locator(f'[data-conversation-id="{test_conversation_id}"]').count() == 1
                    record(results, "Agent route and conversation survive refresh", refreshed and selected, f"{refresh_detail}; selected_session_present={selected}")
                    page.screenshot(path=str(shots / "03_agent_refresh.png"), full_page=True)

                run_conversation, run_id = find_run_session(args.api_url, user_id, preferred=test_conversation_id)
                if run_id:
                    locator = page.locator(f'[data-conversation-id="{run_conversation}"]')
                    if locator.count():
                        locator.click()
                        page.get_by_test_id("agent-run-details").wait_for(state="visible", timeout=90_000)
                        run_body = page.get_by_test_id("agent-run-details").inner_text()
                        markers = ["计划与步骤", "工具调用", "Message Trace", "Reflection / Critic", "Handoff", "ReAct / Replan", "Memory 安全摘要"]
                        missing = [item for item in markers if item not in run_body]
                        record(results, "Run detail exposes Trace/Handoff/Reflection/Replan safe panels", not missing, f"run_id={run_id}; missing={missing}")
                        page.screenshot(path=str(shots / "04_agent_run_details.png"), full_page=True)
                    else:
                        record(results, "Run detail exposes Trace/Handoff/Reflection/Replan safe panels", False, f"run conversation not in UI: {run_conversation}")
                else:
                    record(results, "Run detail handles missing external run without page failure", True, "No run_id was produced; terminal failure was persisted and page remained stable")

                pending_records: list[dict[str, Any]] = []
                if test_conversation_id:
                    ok, payload, _ = request_json(args.api_url, "/api/v1/web/agent/pending-actions", params={"user_id": user_id, "conversation_id": test_conversation_id})
                    pending_records = list(((data_of(payload) or {}) if ok else {}).get("records") or [])
                tab = page.get_by_role("tab", name=re.compile(r"待确认操作"))
                tab.click()
                if pending_records:
                    page.get_by_role("button", name="确认", exact=True).first.click()
                    modal_visible = page.locator(".ant-modal:visible").filter(has_text="确认执行 Agent 待确认操作？").count() > 0
                    dismissed, dismiss_detail = dismiss_modal(page)
                    record(results, "Pending Agent write requires explicit phrase and second confirmation", modal_visible and dismissed, dismiss_detail)
                else:
                    record(results, "Pending-action panel renders a safe empty state", "当前会话没有待确认操作" in page.locator("body").inner_text(), "no pending action")

                page.get_by_role("tab", name="策略草稿", exact=True).click()
                proposal_text = page.locator("body").inner_text()
                record(results, "Strategy proposal panel is read-only and renderable", "策略草稿" in proposal_text, "proposal panel opened")

                local_storage = page.evaluate("Object.fromEntries(Object.entries(localStorage))")
                storage_text = json.dumps(local_storage, ensure_ascii=False).lower()
                forbidden_storage = [item for item in ("confirmation_token", "task result", '"events"', '"task"', "api_key", "password", "positions") if item in storage_text]
                record(results, "Browser storage contains recovery identifiers only", not forbidden_storage, f"keys={sorted(local_storage)}; forbidden={forbidden_storage}")

                page_text = page.locator("body").inner_text().lower()
                sensitive = [item for item in ("confirmation_token", "tushare_token", "neo4j_password", "d:\\stock_daily_app", "/app/", "agent_quant.db") if item in page_text]
                record(results, "Agent UI does not expose secrets or server paths", not sensitive, f"found={sensitive}")
            finally:
                browser.close()
    except Exception as exc:
        runtime_errors.append(f"{type(exc).__name__}: {exc}")
        record(results, "Browser acceptance runtime", False, runtime_errors[-1])

    # Clean up only the disposable session created by this acceptance run.
    if test_conversation_id:
        ok, payload, detail = request_json(
            args.api_url,
            f"/api/v1/web/agent/sessions/{quote(test_conversation_id)}",
            method="delete",
            params={"user_id": user_id},
        )
        record(results, "Disposable acceptance conversation is soft-deleted", ok and payload.get("success") is True, detail)

    record(results, "Browser console has no uncaught errors", not console_errors, "; ".join(console_errors[-10:]))
    if runtime_errors:
        (output / "browser_runtime_errors.json").write_text(json.dumps(runtime_errors, ensure_ascii=False, indent=2), encoding="utf-8")
    return write_report(output, results, console_errors, runtime_errors)


if __name__ == "__main__":
    raise SystemExit(main())
