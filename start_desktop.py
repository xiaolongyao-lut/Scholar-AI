# -*- coding: utf-8 -*-
"""
文献助手 — 真正的单体嵌入式桌面启动器

uvicorn 跑在 daemon 线程内，pywebview 占主线程。
一个进程搞定一切：窗口关闭 → 进程退出 → 无残留。
无需子进程，无需外部浏览器。

参考：
  - github/aiteam控制台参考/QwenPaw-main/src/qwenpaw/cli/desktop_cmd.py
  - github/cua-main/libs/python/bench-ui/bench_ui/child.py
"""

import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from literature_assistant.bootstrap import configure_runtime_paths

configure_runtime_paths()

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv-1" / "Scripts" / "python.exe"
FRONTEND_DIST = ROOT / "frontend" / "dist" / "index.html"

DEFAULT_PORT = 8000
WINDOW_TITLE = "文献助手"
WINDOW_WIDTH = 1440
WINDOW_HEIGHT = 900


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _check_frontend_build() -> bool:
    return FRONTEND_DIST.exists()


def _build_frontend() -> bool:
    print("[启动器] 前端未构建，正在编译...")
    frontend_dir = ROOT / "frontend"
    if not (frontend_dir / "package.json").exists():
        print("[启动器] 前端构建失败: 找不到 frontend/package.json")
        return False
    result = subprocess.run(
        ["npm", "run", "build"],
        cwd=str(frontend_dir),
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"[启动器] 前端构建失败:\n{result.stderr[-500:]}")
        return False
    print("[启动器] 前端构建完成")
    return True


def _wait_for_http(host: str, port: int, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://{host}:{port}/health", timeout=2)
            return True
        except OSError:
            time.sleep(0.3)
    return False


class NativeApi:
    """JS→Python bridge exposed via pywebview js_api."""

    def save_dialog(self, default_name: str = "export.docx") -> str | None:
        import webview
        result = webview.windows[0].create_file_dialog(
            webview.SAVE_DIALOG, save_filename=default_name,
        )
        if result and isinstance(result, tuple) and len(result) > 0:
            return result[0]
        return None

    def open_dialog(self, file_types: tuple = ("PDF Files (*.pdf)",)) -> str | None:
        import webview
        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG, file_types=file_types,
        )
        if result and isinstance(result, tuple) and len(result) > 0:
            return result[0]
        return None


def main() -> None:
    import webview

    # Parse port override
    port = DEFAULT_PORT
    for arg in sys.argv[1:]:
        if arg.isdigit():
            port = int(arg)
            break

    if not _port_available(port):
        port = _find_free_port()
        print(f"[启动器] 端口 {DEFAULT_PORT} 已被占用，使用 {port}")

    # Check / build frontend
    if not _check_frontend_build():
        if not _build_frontend():
            print("[启动器] 无法启动：前端构建失败")
            input("按回车键退出...")
            sys.exit(1)
    print("[启动器] 前端已就绪")

    # Start uvicorn in daemon thread (IN-PROCESS — single process)
    host = "127.0.0.1"

    def _run_server():
        import uvicorn
        from literature_assistant.core.python_adapter_server import app
        uvicorn.run(app, host=host, port=port, log_level="warning")

    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()
    print(f"[启动器] 后端启动中 ({host}:{port})...")

    if not _wait_for_http(host, port, timeout=30):
        print("[启动器] 后端未在 30 秒内就绪，启动失败")
        input("按回车键退出...")
        sys.exit(1)

    url = f"http://{host}:{port}"
    print(f"[启动器] 后端就绪: {url}")

    # Open pywebview native window (blocks main thread)
    api = NativeApi()
    webview.create_window(
        WINDOW_TITLE, url=url,
        width=WINDOW_WIDTH, height=WINDOW_HEIGHT,
        text_select=True, js_api=api, background_color="#FFFFFF",
    )
    print("[启动器] 桌面窗口已打开，关闭窗口将退出程序")
    webview.start(debug=bool(os.environ.get("LITERATURE_ASSISTANT_DEBUG")))

    # Window closed → daemon threads auto-terminate with process exit
    print("[启动器] 窗口已关闭，退出")


if __name__ == "__main__":
    main()
