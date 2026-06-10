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
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Final
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
BROWSER_CACHE_VERSION_FILE: Final[str] = ".frontend_cache_version"
LIGHT_APP_BACKGROUND: Final[str] = "#F7F9FB"
LIGHT_TITLE_TEXT: Final[str] = "#2A3245"
DARK_APP_BACKGROUND: Final[str] = "#111827"
DARK_TITLE_TEXT: Final[str] = "#F8FAFC"


def _show_startup_error(title: str, message: str) -> None:
    """Show a startup failure without blocking double-click launches."""

    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be non-empty")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be non-empty")
    print(f"[启动器] {title}: {message}")
    if sys.platform != "win32":
        return
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        return


def _windows_colorref(hex_color: str) -> int:
    value = hex_color.strip()
    if not (len(value) == 7 and value.startswith("#")):
        raise ValueError(f"Expected #RRGGBB color, got {hex_color!r}")
    red = int(value[1:3], 16)
    green = int(value[3:5], 16)
    blue = int(value[5:7], 16)
    return red | (green << 8) | (blue << 16)


def _is_windows_apps_dark_theme() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            apps_use_light_theme, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return apps_use_light_theme == 0
    except OSError:
        return False


def _apply_windows_titlebar_colors(window: object) -> None:
    if sys.platform != "win32":
        return

    try:
        import ctypes

        native = getattr(window, "native", None)
        handle = getattr(native, "Handle", None)
        if handle is None:
            return

        hwnd = int(handle.ToInt32())
        if hwnd <= 0:
            return

        dark = _is_windows_apps_dark_theme()
        caption = DARK_APP_BACKGROUND if dark else LIGHT_APP_BACKGROUND
        text = DARK_TITLE_TEXT if dark else LIGHT_TITLE_TEXT
        border = caption
        dwm = ctypes.windll.dwmapi

        for attribute, color in (
            (35, caption),  # DWMWA_CAPTION_COLOR
            (34, border),   # DWMWA_BORDER_COLOR
            (36, text),     # DWMWA_TEXT_COLOR
        ):
            value = ctypes.c_int(_windows_colorref(color))
            dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))
    except (AttributeError, OSError, ValueError):
        return


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


def _remove_profile_cache_dir(cache_dir: Path, profile_root: Path) -> None:
    """Delete a browser cache directory only when it is inside the app profile.

    Args:
        cache_dir: Candidate cache directory below the browser profile.
        profile_root: Dedicated browser profile root used by the launcher.

    Raises:
        RuntimeError: If the candidate would delete the profile root itself or
            any path outside the profile boundary.
    """

    if not isinstance(cache_dir, Path):
        raise TypeError("cache_dir must be a pathlib.Path")
    if not isinstance(profile_root, Path):
        raise TypeError("profile_root must be a pathlib.Path")

    resolved_cache = cache_dir.resolve()
    resolved_profile = profile_root.resolve()
    if resolved_cache == resolved_profile or resolved_profile not in resolved_cache.parents:
        raise RuntimeError(f"Refusing to delete cache outside app profile: {cache_dir}")
    if resolved_cache.is_dir():
        shutil.rmtree(resolved_cache)


def _clear_stale_browser_cache(profile_root: Path, cache_version: str) -> None:
    """Clear embedded-browser cache only after the frontend build version changes.

    Args:
        profile_root: Dedicated browser profile root owned by this app.
        cache_version: Non-empty identifier for the current frontend build.

    Raises:
        TypeError: If ``profile_root`` is not a ``Path``.
        ValueError: If ``cache_version`` is empty.
    """

    if not isinstance(profile_root, Path):
        raise TypeError("profile_root must be a pathlib.Path")
    normalized_version = str(cache_version or "").strip()
    if not normalized_version:
        raise ValueError("cache_version must be non-empty")

    marker = profile_root / BROWSER_CACHE_VERSION_FILE
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == normalized_version:
        return

    for relative in (("Default", "Cache"), ("Default", "Code Cache")):
        cache_dir = profile_root.joinpath(*relative)
        try:
            _remove_profile_cache_dir(cache_dir, profile_root)
        except OSError as exc:
            print(f"[启动器] 浏览器缓存清理跳过: {cache_dir.name}: {exc}")

    profile_root.mkdir(parents=True, exist_ok=True)
    marker.write_text(normalized_version, encoding="utf-8")


def _build_frontend() -> bool:
    print("[启动器] 前端未构建，正在编译...")
    frontend_dir = ROOT / "frontend"
    if not (frontend_dir / "package.json").exists():
        print("[启动器] 前端构建失败: 找不到 frontend/package.json")
        return False
    npm_name = "npm.cmd" if sys.platform == "win32" else "npm"
    npm_path = shutil.which(npm_name) or shutil.which("npm")
    if not npm_path:
        print("[启动器] 前端构建失败: 找不到 npm，请先安装 Node.js")
        return False
    result = subprocess.run(
        [npm_path, "run", "build"],
        cwd=str(frontend_dir),
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
            _show_startup_error("启动失败", "前端构建失败，请检查 Node.js/npm 和 frontend 构建日志。")
            sys.exit(1)
    print("[启动器] 前端已就绪")

    # Start uvicorn in daemon thread (IN-PROCESS — single process)
    host = "127.0.0.1"

    # 0.1.8.1 port-bridge: persist the chosen port so the dev frontend
    # (vite proxy) and the installed shell window converge on the same
    # value. Best-effort — never blocks startup.
    try:
        from literature_assistant.core.python_adapter_server import write_api_port_file
        write_api_port_file(port)
    except Exception as _port_exc:
        print(f"[启动器] api-port.json 写入失败（忽略）: {_port_exc}")

    def _run_server():
        import uvicorn
        from literature_assistant.core.python_adapter_server import app
        uvicorn.run(app, host=host, port=port, log_level="warning")

    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()
    print(f"[启动器] 后端启动中 ({host}:{port})...")

    if not _wait_for_http(host, port, timeout=30):
        print("[启动器] 后端未在 30 秒内就绪，启动失败")
        _show_startup_error("启动失败", "后端未在 30 秒内就绪，请检查 runtime_state/logs/backend.log。")
        sys.exit(1)

    url = f"http://{host}:{port}"
    print(f"[启动器] 后端就绪: {url}")

    # Open pywebview native window (blocks main thread)
    api = NativeApi()
    window = webview.create_window(
        WINDOW_TITLE, url=url,
        width=WINDOW_WIDTH, height=WINDOW_HEIGHT,
        text_select=True, js_api=api, background_color=LIGHT_APP_BACKGROUND,
    )
    if window is not None:
        window.events.shown += _apply_windows_titlebar_colors
    print("[启动器] 桌面窗口已打开，关闭窗口将退出程序")
    webview.start(debug=bool(os.environ.get("LITERATURE_ASSISTANT_DEBUG")))

    # Window closed → daemon threads auto-terminate with process exit
    print("[启动器] 窗口已关闭，退出")


if __name__ == "__main__":
    main()
