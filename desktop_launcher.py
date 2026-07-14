from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from app_version import APP_DISPLAY_NAME
from runtime_paths import (
    ensure_runtime_directories,
    get_logs_dir,
    get_resource_root,
    get_runtime_dir,
    get_user_data_root,
    is_frozen_app,
)


HOST = "127.0.0.1"
READY_TIMEOUT_SECONDS = 90


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
            try:
                import fcntl

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


def _log_path(name: str) -> Path:
    path = get_logs_dir() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _append_launcher_log(text: str) -> None:
    path = _log_path("desktop_launcher.log")
    with path.open("a", encoding="utf-8", errors="ignore") as file:
        file.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(sock.getsockname()[1])


def _app_script_path() -> Path:
    app_path = get_resource_root() / "app.py"
    if app_path.exists():
        return app_path
    source_path = Path(__file__).resolve().with_name("app.py")
    if source_path.exists():
        return source_path
    raise FileNotFoundError(f"app.py not found in resource root: {get_resource_root()}")


def _streamlit_child_command(port: int) -> list[str]:
    if is_frozen_app():
        return [sys.executable, "--streamlit-child", "--port", str(port)]
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "--streamlit-child",
        "--port",
        str(port),
    ]


def _wait_for_server(url: str, process: subprocess.Popen, timeout: int) -> None:
    deadline = time.time() + timeout
    health_url = f"{url}/_stcore/health"
    last_error = ""
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Streamlit child exited early with code {process.returncode}.")
        for candidate in (health_url, url):
            try:
                with urllib.request.urlopen(candidate, timeout=2) as response:
                    if response.status < 500:
                        return
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = str(exc)
        time.sleep(0.5)
    raise TimeoutError(f"Streamlit did not become ready within {timeout}s. Last error: {last_error}")


def _terminate_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _open_desktop_window(url: str) -> None:
    try:
        import webview

        webview.create_window(APP_DISPLAY_NAME, url, width=1280, height=860)
        webview.start()
    except Exception as exc:
        _append_launcher_log(f"pywebview unavailable, falling back to browser: {type(exc).__name__}: {exc}")
        webbrowser.open(url)
        print(f"{APP_DISPLAY_NAME} is running at {url}")
        print("Close this terminal or press Ctrl+C to stop the local Streamlit service.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return


def _run_streamlit_child(port: int) -> int:
    ensure_runtime_directories()
    app_path = _app_script_path()
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")

    from streamlit.web import cli as streamlit_cli

    sys.argv = [
        "streamlit",
        "run",
        str(app_path),
        "--global.developmentMode=false",
        f"--server.address={HOST}",
        f"--server.port={int(port)}",
        "--server.headless=true",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
    ]
    return int(streamlit_cli.main() or 0)


def _run_daily_update_child(argv: list[str]) -> int:
    ensure_runtime_directories()
    try:
        from daily_incremental_update import main as daily_update_main

        return int(daily_update_main(argv) or 0)
    except Exception as exc:
        print(f"[Daily Update Child Failed] {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1


def _run_launcher(dry_run: bool = False) -> int:
    ensure_runtime_directories()
    port = _find_free_port()
    url = f"http://{HOST}:{port}"
    command = _streamlit_child_command(port)
    child_log_path = _log_path("streamlit_child.log")

    if dry_run:
        print(json.dumps({
            "mode": "frozen" if is_frozen_app() else "source",
            "url": url,
            "command": command,
            "resource_root": str(get_resource_root()),
            "user_data_root": str(get_user_data_root()),
            "log_path": str(child_log_path),
        }, ensure_ascii=False, indent=2))
        return 0

    lock_path = get_runtime_dir() / "desktop_launcher.lock"
    with SingleInstanceLock(lock_path):
        _append_launcher_log(f"starting Streamlit child: {command}")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["STOCK_DAILY_DESKTOP_MODE"] = "1"
        with child_log_path.open("w", encoding="utf-8", errors="ignore") as log_file:
            process = subprocess.Popen(
                command,
                cwd=str(get_user_data_root() if is_frozen_app() else get_resource_root()),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                env=env,
            )
            try:
                _wait_for_server(url, process, READY_TIMEOUT_SECONDS)
                _append_launcher_log(f"Streamlit ready: {url}")
                _open_desktop_window(url)
                return 0
            finally:
                _append_launcher_log("terminating Streamlit child")
                _terminate_process(process)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="StockDailyApp desktop launcher")
    parser.add_argument("--streamlit-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--daily-update-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true", help="Print launch settings without starting Streamlit.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, remaining = parser.parse_known_args(argv)
    if args.daily_update_child:
        return _run_daily_update_child(remaining)
    if args.streamlit_child:
        if not args.port:
            parser.error("--port is required for --streamlit-child")
        return _run_streamlit_child(args.port)
    return _run_launcher(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
