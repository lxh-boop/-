from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REQUIRED = [
    "application/web_settings_service.py",
    "server/api/routers/web_settings.py",
    "server/api/schemas/settings.py",
    "frontend/src/pages/dashboard/SettingsPage.tsx",
    "frontend/src/components/dashboard/RankingTable.tsx",
    "tests/unit/test_stage6_6_market_config.py",
]


def main() -> int:
    violations: list[str] = []
    for relative in REQUIRED:
        if not (ROOT / relative).exists():
            violations.append(f"required file missing: {relative}")

    settings_api = (ROOT / "frontend/src/api/settingsApi.ts").read_text(encoding="utf-8")
    if "httpClient.put" not in settings_api or "/api/v1/web/settings" not in settings_api:
        violations.append("settings API does not use the protected web settings route")

    settings_page = (ROOT / "frontend/src/pages/dashboard/SettingsPage.tsx").read_text(encoding="utf-8")
    for marker in ("本地模型", "远程 API", "Tushare", "Modal.confirm", "createWriteMeta"):
        if marker not in settings_page:
            violations.append(f"settings UI marker missing: {marker}")
    for forbidden in ("llm_api_key", "tushare_token", "confirmation_token"):
        if forbidden in settings_page:
            violations.append(f"settings UI contains server credential field: {forbidden}")

    ranking = (ROOT / "frontend/src/components/dashboard/RankingTable.tsx").read_text(encoding="utf-8")
    for marker in ("开盘价", "最高价", "最低价", "收盘价"):
        if marker not in ranking:
            violations.append(f"ranking OHLC column missing: {marker}")

    service = (ROOT / "application/web_settings_service.py").read_text(encoding="utf-8")
    for marker in (
        "settings_update_confirmation_required",
        "clear_api_credential",
        "clear_tushare_credential",
        "save_local_config",
        "local_llm_endpoint_must_be_local",
    ):
        if marker not in service:
            violations.append(f"settings safety marker missing: {marker}")

    read_service = (ROOT / "application/web_read_service.py").read_text(encoding="utf-8")
    for marker in ("_attach_signal_date_ohlc", "ohlc_available", '"open", "high", "low", "close"'):
        if marker not in read_service:
            violations.append(f"signal-date OHLC marker missing: {marker}")

    frontend_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (ROOT / "frontend/src").rglob("*")
        if path.is_file() and path.suffix in {".ts", ".tsx"}
    )
    for pattern in (r"llm_api_key", r"tushare_token", r"confirmation_token", r"[A-Za-z]:\\"):
        if re.search(pattern, frontend_text, re.I):
            violations.append(f"frontend contains forbidden private marker: {pattern}")

    report = {
        "stage": "6.6",
        "required_files": len(REQUIRED),
        "violation_count": len(violations),
        "violations": violations,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
