from __future__ import annotations

import subprocess
import sys
import time

import requests


def test_streamlit_smoke_starts_on_temp_port():
    port = "8520"
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
        deadline = time.time() + 45
        last_error = ""
        while time.time() < deadline:
            try:
                response = requests.get(f"http://127.0.0.1:{port}", timeout=2)
                if response.status_code == 200:
                    assert "Streamlit" in response.text or "streamlit" in response.text.lower()
                    return
            except Exception as exc:
                last_error = str(exc)
            time.sleep(1)
        raise AssertionError(f"Streamlit did not respond: {last_error}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
