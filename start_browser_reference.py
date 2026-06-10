# -*- coding: utf-8 -*-
"""
Modular Pipeline — 桌面端一键启动器

启动后端 API 服务，在独立桌面窗口中显示界面（无地址栏、无浏览器 chrome）。
用户只需双击 start.bat 或运行 python start.py 即可使用。
"""

import sys
import subprocess
import time
import urllib.request
import shutil
from pathlib import Path
from typing import Final

from literature_assistant.bootstrap import configure_runtime_paths
from literature_assistant.core.project_paths import app_profile_path


configure_runtime_paths()

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv-1" / "Scripts" / "python.exe"
FRONTEND_DIST = ROOT / "frontend" / "dist" / "index.html"
APP_PROFILE = app_profile_path()

DEFAULT_PORT = 8000
WINDOW_TITLE = "Modular Pipeline — 文献处理工作台"
WINDOW_WIDTH = 1440
WINDOW_HEIGHT = 900
BROWSER_CACHE_VERSION_FILE: Final[str] = ".frontend_cache_version"


def _show_startup_error(title: str, message: str) -> None:
    """Show a startup failure without blocking headless console sessions."""

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


def _find_python() -> str:
    if VENV_PYTHON.exists():
        return str(VENV_PYTHON)
    return sys.executable


def _check_frontend_build() -> bool:
    return FRONTEND_DIST.exists()


def _build_frontend() -> bool:
    print("[启动器] 前端未构建，正在编译...")
    frontend_dir = ROOT / "frontend"
    if not (frontend_dir / "package.json").exists():
        print("[启动器] ❌ 找不到 frontend/package.json")
        return False
    npm_name = "npm.cmd" if sys.platform == "win32" else "npm"
    npm_path = shutil.which(npm_name) or shutil.which("npm")
    if not npm_path:
        print("[启动器] ❌ 找不到 npm，请先安装 Node.js")
        return False
    result = subprocess.run(
        [npm_path, "run", "build"],
        cwd=str(frontend_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"[启动器] ❌ 前端构建失败:\n{result.stderr[-500:]}")
        return False
    print("[启动器] ✅ 前端构建完成")
    return True


def _wait_for_server(port: int, timeout: float = 15.0) -> bool:
    url = f"http://localhost:{port}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)  # noqa: S310
            return True
        except OSError:
            time.sleep(0.3)
    return False


def _start_server(python: str, port: int) -> subprocess.Popen:
    return subprocess.Popen(
        [python, "-m", "uvicorn", "literature_assistant.core.python_adapter_server:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT),
    )


def _find_browser_for_app_mode() -> str | None:
    """Find Edge or Chrome for --app mode (standalone window, no address bar)."""
    candidates = [
        # Microsoft Edge (preferred on Windows)
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        # Google Chrome
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    # Try PATH
    for name in ("msedge", "chrome", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _frontend_cache_version() -> str:
    """Return a stable cache version tied to the built SPA shell.

    Why:
        Hashed Vite assets should not require deleting browser cache on every
        launch. The index mtime is enough to clear stale profile cache only
        after a new frontend build lands.
    """

    if FRONTEND_DIST.exists():
        return str(FRONTEND_DIST.stat().st_mtime_ns)
    return "frontend-dist-missing"


def _remove_cache_dir(cache_dir: Path, profile_root: Path) -> None:
    """Delete one browser cache directory only inside the app profile."""

    resolved_cache = cache_dir.resolve()
    resolved_profile = profile_root.resolve()
    if resolved_cache == resolved_profile or resolved_profile not in resolved_cache.parents:
        raise RuntimeError(f"Refusing to delete cache outside app profile: {cache_dir}")
    if resolved_cache.is_dir():
        shutil.rmtree(resolved_cache)


def _clear_stale_browser_cache(profile_root: Path, cache_version: str) -> None:
    """Clear Edge/Chrome cache only when the frontend build version changes.

    Args:
        profile_root: Dedicated browser profile path passed to ``--user-data-dir``.
        cache_version: Non-empty identifier for the current frontend build.
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
            _remove_cache_dir(cache_dir, profile_root)
        except OSError as exc:
            print(f"[启动器] 浏览器缓存清理跳过: {cache_dir.name}: {exc}")

    profile_root.mkdir(parents=True, exist_ok=True)
    marker.write_text(normalized_version, encoding="utf-8")


def _open_app_window(url: str) -> subprocess.Popen | None:
    """Open a standalone app window using Edge/Chrome --app mode."""
    browser = _find_browser_for_app_mode()
    if not browser:
        return None
    user_data_path = APP_PROFILE
    _clear_stale_browser_cache(user_data_path, _frontend_cache_version())
    user_data = str(user_data_path)
    return subprocess.Popen([
        browser,
        f"--app={url}",
        f"--window-size={WINDOW_WIDTH},{WINDOW_HEIGHT}",
        f"--user-data-dir={user_data}",
        "--disable-extensions",
        "--disable-default-apps",
        "--no-first-run",
    ])


def main() -> None:
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass

    python = _find_python()
    print(f"[启动器] Python: {python}")
    print(f"[启动器] 端口:   {port}")

    # Check / build frontend
    if not _check_frontend_build():
        if not _build_frontend():
            print("[启动器] ❌ 无法启动：前端构建失败")
            _show_startup_error("启动失败", "前端构建失败，请检查 Node.js/npm 和 frontend 构建日志。")
            sys.exit(1)

    print("[启动器] ✅ 前端已就绪")

    # Start backend server
    server = _start_server(python, port)
    print("[启动器] 🚀 后端服务启动中...")

    if not _wait_for_server(port):
        print("[启动器] ❌ 服务未在 15 秒内就绪")
        server.terminate()
        _show_startup_error("启动失败", "后端服务未在 15 秒内就绪，请检查 runtime_state/logs/backend.log。")
        sys.exit(1)

    url = f"http://localhost:{port}"
    print(f"[启动器] ✅ 服务就绪: {url}")

    # Open desktop window
    app_window = _open_app_window(url)
    if app_window:
        print("[启动器] 🖥️  桌面窗口已打开")
        print("[启动器]    关闭窗口将自动停止服务")
        app_window.wait()  # blocks until window is closed
    else:
        # Last resort fallback
        import webbrowser
        print("[启动器] ⚠️  未找到 Edge/Chrome，使用默认浏览器打开")
        webbrowser.open(url)
        try:
            server.wait()
        except KeyboardInterrupt:
            pass

    print("\n[启动器] 窗口已关闭，正在停止服务...")
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
    print("[启动器] 已停止 ✨")


if __name__ == "__main__":
    main()
