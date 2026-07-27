from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from playwright.sync_api import Page, sync_playwright


def record(results: list[dict[str, Any]], name: str, success: bool, detail: str) -> None:
    results.append({"name": name, "success": bool(success), "detail": str(detail)})


def request_json(
    api_url: str,
    path: str,
    *,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
    timeout: int = 60,
) -> tuple[bool, dict[str, Any], str]:
    try:
        response = requests.request(
            method,
            f"{api_url}{path}",
            json=json_body,
            timeout=timeout,
        )
        payload = response.json() if response.content else {}
        return response.status_code == 200, payload if isinstance(payload, dict) else {}, f"status={response.status_code}"
    except Exception as exc:
        return False, {}, f"{type(exc).__name__}: {exc}"


def data_of(payload: dict[str, Any]) -> Any:
    return payload.get("data") if payload.get("success") is True else None


def format_console_message(item: Any) -> str:
    try:
        return f"{item.type}: {item.text}"
    except Exception:
        return str(item)


def wait_heading(page: Page, text: str, timeout: int = 60_000) -> tuple[bool, str]:
    try:
        page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout)
        return True, f"visible={text}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def load_regression(path: str) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    if not path:
        return [], [], []
    result_path = Path(path)
    if not result_path.exists():
        return [
            {
                "name": "Stage 6.5 browser regression result is available",
                "success": False,
                "detail": f"missing={result_path}",
            }
        ], [], []
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8-sig"))
        results = [
            {
                "name": f"Stage 6.5 regression: {item.get('name')}",
                "success": bool(item.get("success")),
                "detail": str(item.get("detail") or ""),
            }
            for item in payload.get("results", [])
        ]
        return results, list(payload.get("console_errors") or []), list(payload.get("runtime_errors") or [])
    except Exception as exc:
        return [
            {
                "name": "Stage 6.5 browser regression result is readable",
                "success": False,
                "detail": f"{type(exc).__name__}: {exc}",
            }
        ], [], []


def write_report(
    output: Path,
    results: list[dict[str, Any]],
    console_errors: list[str],
    runtime_errors: list[str],
) -> int:
    passed = sum(1 for item in results if item["success"])
    failed = len(results) - passed
    payload = {
        "stage": "6.6",
        "passed": passed,
        "failed": failed,
        "results": results,
        "console_errors": console_errors,
        "runtime_errors": runtime_errors,
        "generated_at": datetime.now().astimezone().isoformat(),
    }
    (output / "browser_test_result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Stage 6.6 Browser Acceptance",
        "",
        f"- Passed: {passed}",
        f"- Failed: {failed}",
        "",
        "| Result | Check | Detail |",
        "|---|---|---|",
    ]
    for item in results:
        status = "PASS" if item["success"] else "FAIL"
        detail = str(item["detail"]).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {status} | {item['name']} | {detail} |")
    if console_errors:
        lines.extend(["", "## Browser console errors", "", "```text", *console_errors[-30:], "```"])
    if runtime_errors:
        lines.extend(["", "## Runtime errors", "", "```text", *runtime_errors[-30:], "```"])
    (output / "acceptance_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"passed": passed, "failed": failed}, ensure_ascii=False))
    return 1 if failed else 0


def public_update_payload(settings: dict[str, Any], *, confirmed: bool) -> dict[str, Any]:
    configuration = dict(settings.get("configuration") or {})
    api = dict(configuration.get("api") or {})
    local = dict(configuration.get("local") or {})
    return {
        "request_id": f"stage66-request-{int(time.time() * 1000)}",
        "idempotency_key": f"stage66-idempotency-{int(time.time() * 1000)}",
        "confirmed": confirmed,
        "llm_mode": str(configuration.get("llm_mode") or "api"),
        "api_provider": str(api.get("provider") or "openai_compatible"),
        "api_base_url": str(api.get("base_url") or ""),
        "api_model": str(api.get("model") or ""),
        "api_credential": None,
        "clear_api_credential": False,
        "local_base_url": str(local.get("base_url") or "http://127.0.0.1:11434/v1"),
        "local_model": str(local.get("model") or "stock-agent-qwen3-4b"),
        "tushare_credential": None,
        "clear_tushare_credential": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:3000")
    parser.add_argument("--api-url", default="http://127.0.0.1:8010")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--regression-result", default="")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    shots = output / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)

    results, console_errors, runtime_errors = load_regression(args.regression_result)

    ok, settings_payload, detail = request_json(args.api_url, "/api/v1/web/settings")
    settings = data_of(settings_payload) if ok else None
    settings = settings if isinstance(settings, dict) else {}
    encoded_settings = json.dumps(settings_payload, ensure_ascii=False).lower()
    forbidden_public = [
        marker
        for marker in ("llm_api_key", "tushare_token", "confirmation_token", "agent_quant.db", "d:\\stock_daily_app", "/app/")
        if marker in encoded_settings
    ]
    configuration = settings.get("configuration") if isinstance(settings, dict) else None
    record(
        results,
        "Settings API is writable and returns editable public configuration",
        ok and settings_payload.get("success") is True and settings.get("read_only") is False and isinstance(configuration, dict),
        f"{detail}; read_only={settings.get('read_only')}; configuration={isinstance(configuration, dict)}",
    )
    record(
        results,
        "Settings response contains no secret or server-path material",
        not forbidden_public,
        f"forbidden={forbidden_public}",
    )

    ok, ranking_payload, detail = request_json(args.api_url, "/api/v1/web/dashboard/rankings?offset=0&limit=100")
    ranking = data_of(ranking_payload) if ok else None
    records = list((ranking or {}).get("records") or []) if isinstance(ranking, dict) else []
    columns_present = bool(records) and all(key in records[0] for key in ("open", "high", "low", "close", "ohlc_available"))
    matched = sum(1 for item in records if item.get("ohlc_available") is True)
    record(
        results,
        "Ranking API exposes signal-date OHLC fields",
        ok and columns_present,
        f"{detail}; records={len(records)}; fields={columns_present}",
    )
    record(
        results,
        "Ranking API matched signal-date OHLC data",
        matched > 0,
        f"matched={matched}; total={len(records)}",
    )

    if settings:
        unconfirmed = public_update_payload(settings, confirmed=False)
        ok, rejected_payload, detail = request_json(
            args.api_url,
            "/api/v1/web/settings",
            method="PUT",
            json_body=unconfirmed,
        )
        reason = str((((rejected_payload.get("error") or {}).get("details") or {}).get("reason") or ""))
        record(
            results,
            "Settings write requires explicit confirmation",
            ok and rejected_payload.get("success") is False and reason == "settings_update_confirmation_required",
            f"{detail}; success={rejected_payload.get('success')}; reason={reason}",
        )

        confirmed = public_update_payload(settings, confirmed=True)
        ok, saved_payload, detail = request_json(
            args.api_url,
            "/api/v1/web/settings",
            method="PUT",
            json_body=confirmed,
        )
        saved_encoded = json.dumps(saved_payload, ensure_ascii=False).lower()
        leaked = [
            marker
            for marker in ("llm_api_key", "tushare_token", "api_credential", "tushare_credential", "confirmation_token")
            if marker in saved_encoded
        ]
        record(
            results,
            "Confirmed no-op settings write succeeds without replacing blank secrets",
            ok and saved_payload.get("success") is True,
            f"{detail}; success={saved_payload.get('success')}",
        )
        record(
            results,
            "Settings write response never echoes credential fields",
            not leaked,
            f"leaked_fields={leaked}",
        )

        ok_after, after_payload, after_detail = request_json(args.api_url, "/api/v1/web/settings")
        after = data_of(after_payload) if ok_after else {}
        before_credentials = settings.get("credentials") or {}
        after_credentials = (after or {}).get("credentials") or {}
        record(
            results,
            "Blank secret inputs preserve existing credential status",
            ok_after and before_credentials == after_credentials,
            f"{after_detail}; before={before_credentials}; after={after_credentials}",
        )

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=not args.headed)
            page = browser.new_page(viewport={"width": 1680, "height": 1050})
            page.set_default_timeout(90_000)
            page.on("console", lambda item: console_errors.append(format_console_message(item)) if item.type == "error" else None)
            page.on("pageerror", lambda error: console_errors.append(str(error)))
            try:
                page.goto(f"{args.url}/dashboard", wait_until="domcontentloaded", timeout=120_000)
                ready, ready_detail = wait_heading(page, "首页 / 预测排名")
                body = page.locator("body").inner_text()
                labels = [label for label in ("开盘价", "最高价", "最低价", "收盘价") if label in body]
                record(results, "Dashboard renders the ranking page", ready, ready_detail)
                record(results, "Dashboard table displays all OHLC columns", len(labels) == 4, f"labels={labels}")
                page.screenshot(path=str(shots / "08_dashboard_ohlc.png"), full_page=True)

                page.goto(f"{args.url}/settings", wait_until="domcontentloaded", timeout=120_000)
                ready, ready_detail = wait_heading(page, "系统设置")
                body = page.locator("body").inner_text()
                ui_markers = [item for item in ("本地模型", "远程 API", "保存配置", "Tushare 配置") if item in body]
                record(results, "Editable settings page renders", ready and len(ui_markers) == 4, f"{ready_detail}; markers={ui_markers}")

                secret_inputs = page.locator('input[type="password"]')
                secret_values = [secret_inputs.nth(index).input_value() for index in range(secret_inputs.count())]
                record(
                    results,
                    "Credential inputs are never prefilled",
                    bool(secret_values) and all(not value for value in secret_values),
                    f"input_count={len(secret_values)}; nonempty={sum(1 for value in secret_values if value)}",
                )
                page.screenshot(path=str(shots / "09_settings_editor.png"), full_page=True)

                save_button = page.get_by_role("button", name="保存配置", exact=True)
                save_button.click(timeout=30_000)
                modal = page.locator(".ant-modal:visible").filter(has_text="确认保存运行配置？")
                modal.wait_for(state="visible", timeout=30_000)
                record(results, "Settings save is protected by browser confirmation", modal.count() > 0, f"modal_count={modal.count()}")
                page.screenshot(path=str(shots / "10_settings_confirmation.png"), full_page=True)
                cancel = modal.locator(".ant-modal-confirm-btns .ant-btn-default")
                if cancel.count():
                    cancel.first.click(force=True)
                else:
                    page.keyboard.press("Escape")
            finally:
                browser.close()
    except Exception as exc:
        runtime_errors.append(f"{type(exc).__name__}: {exc}")
        record(results, "Stage 6.6 browser flow completed", False, f"{type(exc).__name__}: {exc}")

    meaningful_console = [
        item
        for item in console_errors
        if not re.search(r"favicon|ResizeObserver loop", item, re.I)
    ]
    record(
        results,
        "Browser has no uncaught console errors",
        not meaningful_console,
        f"errors={meaningful_console[-10:]}",
    )
    return write_report(output, results, meaningful_console, runtime_errors)


if __name__ == "__main__":
    raise SystemExit(main())
