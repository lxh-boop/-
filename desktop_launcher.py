from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from app_version import APP_DISPLAY_NAME
from runtime_paths import ensure_runtime_directories, get_logs_dir, get_runtime_dir

DEFAULT_FRONTEND_URL = "http://127.0.0.1:3000"
READY_TIMEOUT_SECONDS = 30


class SingleInstanceLock:
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._file = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.lock_path.open("a+", encoding="utf-8")
        if os.name == "nt":
            import msvcrt
            try:
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("StockDailyApp is already running.") from exc
        else:
            import fcntl
            try:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("StockDailyApp is already running.") from exc
        self._file.seek(0)
        self._file.truncate()
        self._file.write(str(os.getpid()))
        self._file.flush()
        return self

    def __exit__(self, exc_type, exc, tb):
        if not self._file:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()


def _append_launcher_log(text: str) -> None:
    path = get_logs_dir() / "desktop_launcher.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", errors="ignore") as file:
        file.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")


def _health_url(frontend_url: str) -> str:
    return frontend_url.rstrip("/") + "/healthz"


def _wait_for_frontend(frontend_url: str, timeout: int) -> None:
    deadline = time.time() + max(1, int(timeout))
    last_error = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(_health_url(frontend_url), timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise TimeoutError(
        "React frontend is not available. Start D:\\google\\D_google_stage_06_5_build_and_start.bat "
        f"and retry. Last error: {last_error}"
    )


def _open_window(url: str) -> None:
    try:
        import webview
        webview.create_window(APP_DISPLAY_NAME, url, width=1280, height=860)
        webview.start()
    except Exception as exc:
        _append_launcher_log(
            f"pywebview unavailable; using browser: {type(exc).__name__}: {exc}"
        )
        webbrowser.open(url)


def _run_daily_update_child(argv: list[str]) -> int:
    ensure_runtime_directories()
    try:
        from daily_incremental_update import main as daily_update_main
        return int(daily_update_main(argv) or 0)
    except Exception as exc:
        print(f"[Daily Update Child Failed] {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="StockDailyApp React launcher")
    parser.add_argument("--daily-update-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--url",
        default=os.environ.get("STOCK_APP_FRONTEND_URL", DEFAULT_FRONTEND_URL),
        help="Production React frontend URL.",
    )
    parser.add_argument("--timeout", type=int, default=READY_TIMEOUT_SECONDS)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, remaining = parser.parse_known_args(argv)
    if args.daily_update_child:
        return _run_daily_update_child(remaining)

    url = str(args.url).rstrip("/")
    if args.dry_run:
        print(json.dumps({"frontend_url": url, "health_url": _health_url(url)}, ensure_ascii=False, indent=2))
        return 0

    ensure_runtime_directories()
    with SingleInstanceLock(get_runtime_dir() / "desktop_launcher.lock"):
        _append_launcher_log(f"waiting for production React frontend: {url}")
        _wait_for_frontend(url, args.timeout)
        _append_launcher_log(f"opening production React frontend: {url}")
        _open_window(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
