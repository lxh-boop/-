from __future__ import annotations

import subprocess
import sys
import time

import pytest
import requests


def test_app_playwright_smoke(page):
    port = "8521"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "app.py",
            "--server.port",
            port,
            "--server.headless",
            "true",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                if requests.get(f"http://127.0.0.1:{port}", timeout=2).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            pytest.fail("Streamlit did not start for Playwright test")

        page.goto(f"http://127.0.0.1:{port}", wait_until="networkidle")
        page.get_by_text("A股每日股票评分系统").wait_for(timeout=30000)
        page.get_by_text("不构成投资建议").first.wait_for(timeout=30000)
        page.get_by_role("tab", name="模型搜索与回测").click()
        page.get_by_text("模型搜索与回测结果").wait_for(timeout=30000)
        page.get_by_text("所选方案历史净值曲线").wait_for(timeout=30000)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
