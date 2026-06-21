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
import urllib.parse
import base64
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
from pathlib import Path

from literature_assistant.bootstrap import configure_runtime_paths

configure_runtime_paths()

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv-1" / "Scripts" / "python.exe"
FRONTEND_ROOT = ROOT / "frontend"
FRONTEND_DIST = FRONTEND_ROOT / "dist" / "index.html"
DESKTOP_PROFILE_ROOT: Final[Path] = ROOT / "workspace_artifacts" / "runtime_state" / "desktop_webview_profile"
FRONTEND_BUILD_INPUTS: Final[tuple[Path, ...]] = (
    FRONTEND_ROOT / "src",
    FRONTEND_ROOT / "public",
    FRONTEND_ROOT / "index.html",
    FRONTEND_ROOT / "package.json",
    FRONTEND_ROOT / "package-lock.json",
    FRONTEND_ROOT / "vite.config.ts",
    FRONTEND_ROOT / "tailwind.config.js",
    FRONTEND_ROOT / "postcss.config.js",
    FRONTEND_ROOT / "tsconfig.json",
)


def _load_dotenv_into_environ(env_path: Path) -> int:
    """Load KEY=VALUE pairs from ``.env`` into ``os.environ`` without overriding existing keys.

    Why: vite (browser dev path) auto-sources .env, but the embedded uvicorn here
    runs in a daemon thread of a fresh Python process and does not. SSRF policy
    in `provider_endpoint_policy.py` reads these vars at module import; missing
    them rejects every chat / rerank call (verified 2026-06-13 desktop test).

    Format contract (what `.env` in this repo actually uses):
      - Lines starting with `#` or `##` are comments.
      - Blank lines are skipped.
      - One assignment per line: `KEY=VALUE` (no quoting, no `${var}` expansion).
      - Duplicate keys: later wins (matches existing `runtime_env.env_value()` semantic).

    Shell-injected env (e.g. user already exported a key) wins over .env — this
    matches dotenv-cli `--no-override` and keeps CI / explicit-override workflows
    working.

    Returns the number of keys loaded (0 if the file is absent or unreadable).
    """
    if not isinstance(env_path, Path):
        raise TypeError("env_path must be a pathlib.Path")
    if not env_path.is_file():
        return 0
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return 0
    # Two-pass: collect every well-formed assignment with last-wins inside the file,
    # then write to os.environ skipping any key shell already set.
    file_pairs: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        file_pairs[key] = value.strip()  # last wins inside the file
    loaded = 0
    for key, value in file_pairs.items():
        if key in os.environ:
            continue  # shell-injected wins over .env
        os.environ[key] = value
        loaded += 1
    return loaded


_DOTENV_LOADED_KEYS = _load_dotenv_into_environ(ROOT / ".env")
if _DOTENV_LOADED_KEYS:
    print(f"[启动器] .env 已加载 {_DOTENV_LOADED_KEYS} 项 (shell 已存在的 key 不覆盖)")

DEFAULT_PORT = 8000
WINDOW_TITLE = "文献助手"
WINDOW_WIDTH = 1440
WINDOW_HEIGHT = 900
WINDOW_MIN_WIDTH = 960
WINDOW_MIN_HEIGHT = 700
WINDOW_SCREEN_MARGIN = 32
BROWSER_CACHE_VERSION_FILE: Final[str] = ".frontend_cache_version"
LIGHT_APP_BACKGROUND: Final[str] = "#F7F9FB"
LIGHT_TITLE_TEXT: Final[str] = "#2A3245"
DARK_APP_BACKGROUND: Final[str] = "#111827"
DARK_TITLE_TEXT: Final[str] = "#F8FAFC"
_DESKTOP_SINGLE_INSTANCE_MUTEX_HANDLE: object | None = None


@dataclass(frozen=True)
class DesktopRect:
    """Native desktop rectangle using left/top/right/bottom coordinates."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)


@dataclass(frozen=True)
class DesktopWindowGeometry:
    """pywebview window geometry chosen to fit inside a visible work area."""

    width: int
    height: int
    x: int | None
    y: int | None


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


def _desktop_single_instance_mutex_name(root: Path) -> str:
    """Return a repository-scoped Windows mutex name for the desktop app.

    Args:
        root: Repository root used to disambiguate local checkouts.

    Returns:
        A Windows local-session mutex name containing only stable ASCII
        characters.
    """

    if not isinstance(root, Path):
        raise TypeError("root must be a pathlib.Path")
    digest = hashlib.sha256(str(root.resolve()).casefold().encode("utf-8")).hexdigest()[:16]
    return f"Local\\ScholarAI_Desktop_{digest}"


def _acquire_desktop_single_instance(root: Path = ROOT) -> bool:
    """Acquire the source-desktop single-instance guard.

    Args:
        root: Repository root whose desktop process should be unique.

    Returns:
        ``True`` when this process owns the guard, or ``False`` when another
        instance for the same checkout is already running.

    Why:
        MCP hosts can restart stdio wrappers concurrently. A Windows mutex keeps
        those wrapper races from opening multiple native desktop windows.
    """

    if not isinstance(root, Path):
        raise TypeError("root must be a pathlib.Path")
    if sys.platform != "win32":
        return True

    global _DESKTOP_SINGLE_INSTANCE_MUTEX_HANDLE
    if _DESKTOP_SINGLE_INSTANCE_MUTEX_HANDLE is not None:
        return True

    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool
        handle = kernel32.CreateMutexW(None, False, _desktop_single_instance_mutex_name(root))
        if not handle:
            return True
        error_already_exists = 183
        if ctypes.get_last_error() == error_already_exists:
            kernel32.CloseHandle(handle)
            return False
        _DESKTOP_SINGLE_INSTANCE_MUTEX_HANDLE = handle
        return True
    except Exception:
        return True


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
    """Apply DWM title-bar colors before WinForms exposes async window events.

    Args:
        window: pywebview window whose native WinForms form is already created.

    Why:
        pywebview's ordinary window events run Python handlers on separate
        threads. Touching the WinForms handle from those handlers can surface
        pythonnet shutdown/conversion failures during close. `before_show` is a
        synchronous event in the WinForms creation path, so it keeps this native
        handle access on the GUI-owned path.
    """
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


def _fit_desktop_dimension(requested: int, available: int, minimum: int, margin: int) -> int:
    """Fit one requested window dimension inside an available desktop axis."""

    if requested <= 0:
        raise ValueError("requested dimension must be positive")
    if minimum <= 0:
        raise ValueError("minimum dimension must be positive")
    if margin < 0:
        raise ValueError("margin must be non-negative")
    if available <= 0:
        return requested
    usable = max(1, available - (margin * 2))
    if usable >= minimum:
        return min(requested, usable)
    return usable


def _center_desktop_window(
    work_area: DesktopRect,
    *,
    requested_width: int = WINDOW_WIDTH,
    requested_height: int = WINDOW_HEIGHT,
    minimum_width: int = WINDOW_MIN_WIDTH,
    minimum_height: int = WINDOW_MIN_HEIGHT,
    margin: int = WINDOW_SCREEN_MARGIN,
) -> DesktopWindowGeometry:
    """Return a pywebview geometry that is centered and fits inside ``work_area``."""

    if work_area.width <= 0 or work_area.height <= 0:
        raise ValueError("work_area must have positive width and height")
    width = _fit_desktop_dimension(requested_width, work_area.width, minimum_width, margin)
    height = _fit_desktop_dimension(requested_height, work_area.height, minimum_height, margin)
    x = work_area.left + max(0, (work_area.width - width) // 2)
    y = work_area.top + max(0, (work_area.height - height) // 2)
    return DesktopWindowGeometry(width=width, height=height, x=x, y=y)


def _scale_desktop_rect(rect: DesktopRect, scale: float) -> DesktopRect:
    """Convert a physical Windows rectangle into pywebview logical coordinates."""

    if scale <= 0:
        raise ValueError("scale must be positive")
    return DesktopRect(
        left=round(rect.left / scale),
        top=round(rect.top / scale),
        right=round(rect.right / scale),
        bottom=round(rect.bottom / scale),
    )


def _windows_dpi_scale() -> float:
    """Return the Windows DPI scale used by pywebview logical window units."""

    if sys.platform != "win32":
        return 1.0
    try:
        import ctypes

        get_dpi_for_system = ctypes.windll.user32.GetDpiForSystem
        get_dpi_for_system.restype = ctypes.c_uint
        dpi = int(get_dpi_for_system())
    except Exception:
        dpi = 96
    if dpi <= 0:
        return 1.0
    return max(1.0, dpi / 96.0)


def _primary_desktop_work_area() -> DesktopRect | None:
    """Return the primary Windows work area in pywebview logical coordinates."""

    if sys.platform != "win32":
        return None
    try:
        import ctypes
    except Exception:
        return None

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    SPI_GETWORKAREA = 0x0030
    user32 = ctypes.windll.user32
    rect = RECT()
    try:
        ok = bool(user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0))
    except Exception:
        ok = False
    scale = _windows_dpi_scale()
    if ok and rect.right > rect.left and rect.bottom > rect.top:
        return _scale_desktop_rect(DesktopRect(
            left=int(rect.left),
            top=int(rect.top),
            right=int(rect.right),
            bottom=int(rect.bottom),
        ), scale)
    try:
        width = int(user32.GetSystemMetrics(0))
        height = int(user32.GetSystemMetrics(1))
    except Exception:
        return None
    if width <= 0 or height <= 0:
        return None
    return _scale_desktop_rect(DesktopRect(left=0, top=0, right=width, bottom=height), scale)


def _enable_windows_dpi_awareness() -> bool:
    """Request DPI-aware Win32 coordinates before creating the pywebview window."""

    if sys.platform != "win32":
        return False
    try:
        import ctypes
    except Exception:
        return False

    error_access_denied = 5
    try:
        set_context = ctypes.windll.user32.SetProcessDpiAwarenessContext
        set_context.argtypes = [ctypes.c_void_p]
        set_context.restype = ctypes.c_bool
        if bool(set_context(ctypes.c_void_p(-4))):  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            return True
        if int(ctypes.get_last_error()) == error_access_denied:
            return True
    except Exception:
        pass

    try:
        set_process_awareness = ctypes.windll.shcore.SetProcessDpiAwareness
        set_process_awareness.argtypes = [ctypes.c_int]
        set_process_awareness.restype = ctypes.c_long
        result = int(set_process_awareness(2))  # PROCESS_PER_MONITOR_DPI_AWARE
        if result in (0, -2147024891):  # S_OK or E_ACCESSDENIED/already set
            return True
    except Exception:
        pass

    try:
        set_dpi_aware = ctypes.windll.user32.SetProcessDPIAware
        set_dpi_aware.restype = ctypes.c_bool
        if bool(set_dpi_aware()):
            return True
        return int(ctypes.get_last_error()) == error_access_denied
    except Exception:
        return False


def _desktop_window_geometry() -> DesktopWindowGeometry:
    """Choose the default source-desktop window geometry."""

    work_area = _primary_desktop_work_area()
    if work_area is None:
        return DesktopWindowGeometry(width=WINDOW_WIDTH, height=WINDOW_HEIGHT, x=None, y=None)
    return _center_desktop_window(work_area)


def _install_reload_hotkeys(window: object) -> None:
    """Install desktop reload keybindings after the webview content is ready.

    Args:
        window: pywebview window object with `events.loaded` and `evaluate_js`.

    Why:
        `shown` handlers are asynchronous in pywebview. Installing this script
        from `webview.start(func=...)` avoids keeping extra event callbacks on
        the close path while still preserving F5/Ctrl+R behavior.
    """
    events = getattr(window, "events", None)
    loaded = getattr(events, "loaded", None)
    wait = getattr(loaded, "wait", None)
    if not callable(wait):
        return
    if not wait(20):
        return
    try:
        evaluate_js = getattr(window, "evaluate_js")
    except AttributeError:
        return
    try:
        evaluate_js("""
        (function(){
          if (window.__litReloadHotkeyInstalled) return;
          window.__litReloadHotkeyInstalled = true;
          function isReload(e){
            return e.key === 'F5'
              || (e.key === 'r' && (e.ctrlKey || e.metaKey))
              || (e.key === 'R' && (e.ctrlKey || e.metaKey));
          }
          window.addEventListener('keydown', function(e){
            if (!isReload(e)) return;
            e.preventDefault();
            e.stopPropagation();
            if (window.pywebview && window.pywebview.api && window.pywebview.api.reload_window) {
              window.pywebview.api.reload_window();
            } else {
              window.location.reload();
            }
          }, true);
        })();
        """)
    except Exception:
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


def _latest_mtime(path: Path) -> float:
    """Return the newest mtime under a frontend input path.

    Why: the desktop launcher serves `frontend/dist`; if source files are newer
    than dist, the user sees stale UI even though the source has changed.
    """

    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path")
    if not path.exists():
        return 0.0
    if path.is_file():
        return path.stat().st_mtime
    newest = path.stat().st_mtime
    for child in path.rglob("*"):
        if child.is_file():
            newest = max(newest, child.stat().st_mtime)
    return newest


def _frontend_build_is_current() -> bool:
    """Return true when the existing dist is newer than frontend source inputs."""

    if not FRONTEND_DIST.is_file():
        return False
    dist_mtime = FRONTEND_DIST.stat().st_mtime
    return all(_latest_mtime(path) <= dist_mtime for path in FRONTEND_BUILD_INPUTS)


def _frontend_cache_version() -> str:
    """Return a browser-cache version tied to the built SPA shell.

    Raises:
        FileNotFoundError: If the frontend build has not produced index.html.
    """

    if not FRONTEND_DIST.is_file():
        raise FileNotFoundError(f"Frontend build not found: {FRONTEND_DIST}")
    stat_result = FRONTEND_DIST.stat()
    return f"{stat_result.st_mtime_ns}:{stat_result.st_size}"


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
    print("[启动器] 前端构建已过期或不存在，正在编译...")
    frontend_dir = FRONTEND_ROOT
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
        encoding="utf-8",
        errors="replace",
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


def _normalize_desktop_initial_path(value: str | None) -> str:
    """Return a safe SPA path for the initial pywebview URL.

    Args:
        value: Optional path/query string from
            ``LITERATURE_ASSISTANT_DESKTOP_INITIAL_PATH``.

    Returns:
        A root-relative path and optional query string.

    Raises:
        ValueError: If the value is absolute, protocol-relative, contains a
            fragment, backslashes, traversal segments, or control characters.
    """

    if value is None or not value.strip():
        return "/"
    candidate = value.strip()
    if "\\" in candidate:
        raise ValueError("desktop initial path must not contain backslashes")
    if any(ord(char) < 32 for char in candidate):
        raise ValueError("desktop initial path must not contain control characters")
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        raise ValueError("desktop initial path must be root-relative")
    if parsed.fragment:
        raise ValueError("desktop initial path must not contain a fragment")
    if not parsed.path.startswith("/") or parsed.path.startswith("//"):
        raise ValueError("desktop initial path must start with a single slash")
    parts = [part for part in parsed.path.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise ValueError("desktop initial path must not contain traversal segments")
    path = parsed.path or "/"
    return urllib.parse.urlunsplit(("", "", path, parsed.query, ""))


def _build_desktop_frontend_url(base_url: str, initial_path: str | None) -> str:
    """Join a loopback base URL with a safe SPA initial path."""

    normalized_base = base_url.rstrip("/")
    if not normalized_base.startswith("http://127.0.0.1:"):
        raise ValueError("desktop base URL must be a loopback URL")
    path = _normalize_desktop_initial_path(initial_path)
    return f"{normalized_base}{path}"


def _first_dialog_path(result: Sequence[str] | str | None) -> str | None:
    """Normalize pywebview file-dialog results for the JS bridge.

    Args:
        result: ``None`` on cancel, one path string, or a sequence whose first
            item is the selected path.

    Returns:
        A non-empty path string, or ``None`` when no selection was made.
    """
    if result is None:
        return None
    if isinstance(result, str):
        path = result.strip()
        return path or None
    if not isinstance(result, Sequence):
        raise TypeError("dialog result must be None, a string, or a sequence of strings")
    if not result:
        return None
    first = result[0]
    if not isinstance(first, str):
        raise TypeError("dialog result path must be a string")
    path = first.strip()
    return path or None


class NativeApi:
    """JS→Python bridge exposed via pywebview js_api."""

    def save_dialog(self, default_name: str = "export.docx") -> str | None:
        """Return one selected save path as a JSON-serializable string.

        Args:
            default_name: Non-empty filename shown by the native save dialog.

        Returns:
            The selected local path, or ``None`` when the user cancels.
        """
        if not isinstance(default_name, str) or not default_name.strip():
            raise ValueError("default_name must be a non-empty string")
        import webview

        result = webview.windows[0].create_file_dialog(
            webview.SAVE_DIALOG, save_filename=default_name,
        )
        return _first_dialog_path(result)

    def open_dialog(self, file_types: Sequence[str] = ("PDF Files (*.pdf)",)) -> str | None:
        """Return one selected open path as a JSON-serializable string.

        Args:
            file_types: pywebview file filter strings such as
                ``"PDF Files (*.pdf)"``.

        Returns:
            The selected local path, or ``None`` when the user cancels.
        """
        if not isinstance(file_types, Sequence) or isinstance(file_types, (str, bytes)):
            raise TypeError("file_types must be a sequence of strings")
        normalized_types = tuple(file_type for file_type in file_types if isinstance(file_type, str) and file_type.strip())
        if not normalized_types:
            raise ValueError("file_types must contain at least one non-empty string")
        import webview

        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG, file_types=normalized_types,
        )
        return _first_dialog_path(result)

    def folder_dialog(self) -> str | None:
        """Return one selected local directory path.

        Returns:
            The selected local directory path, or ``None`` when the user cancels.
        """
        import webview

        result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        return _first_dialog_path(result)

    def save_bytes(self, default_name: str, content_base64: str) -> str | None:
        """Persist a browser-generated export through the native save dialog.

        Args:
            default_name: Non-empty filename shown by the native save dialog.
            content_base64: Standard base64 payload generated by the frontend.

        Returns:
            The selected local path, or ``None`` when the user cancels.

        Raises:
            ValueError: If either input is empty or the payload is not valid
                base64 bytes.
        """
        if not isinstance(default_name, str) or not default_name.strip():
            raise ValueError("default_name must be a non-empty string")
        if not isinstance(content_base64, str) or not content_base64.strip():
            raise ValueError("content_base64 must be a non-empty string")
        target = self.save_dialog(default_name)
        if target is None:
            return None
        try:
            payload = base64.b64decode(content_base64, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("content_base64 must be valid base64") from exc
        output_path = Path(target).expanduser()
        if output_path.exists() and output_path.is_dir():
            raise ValueError("save target must be a file path, not a directory")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(payload)
        return str(output_path)

    def minimize_window(self) -> None:
        import webview
        webview.windows[0].minimize()

    def maximize_window(self) -> None:
        import webview
        webview.windows[0].toggle_fullscreen()

    def close_window(self) -> None:
        import webview
        webview.windows[0].destroy()

    def reload_window(self) -> None:
        """B13 (2026-06-13): pywebview disables F5/Ctrl+R by default. Expose a
        Python-side reload so the injected keyboard handler can rebind it."""
        import webview
        window = webview.windows[0]
        # Prefer load_url so cache is bypassed in dev. evaluate_js fallback
        # if load_url is not available on the bound backend (Edge/Chromium).
        try:
            current = window.get_current_url()
            if current:
                window.load_url(current)
                return
        except Exception:
            pass
        try:
            window.evaluate_js("window.location.reload(true)")
        except Exception:
            pass


def main() -> None:
    if not _acquire_desktop_single_instance():
        print("[启动器] 已有文献助手桌面实例在运行，本次启动退出")
        return

    dpi_aware = _enable_windows_dpi_awareness()
    import webview

    if dpi_aware:
        print("[启动器] Windows DPI awareness 已启用")

    # Parse port override
    port = DEFAULT_PORT
    for arg in sys.argv[1:]:
        if arg.isdigit():
            port = int(arg)
            break

    requested_port = port
    if not _port_available(port):
        port = _find_free_port()
        print(f"[启动器] 端口 {requested_port} 已被占用，使用 {port}")

    # Check / build frontend
    if not _frontend_build_is_current():
        if not _build_frontend():
            print("[启动器] 无法启动：前端构建失败")
            _show_startup_error("启动失败", "前端构建失败，请检查 Node.js/npm 和 frontend 构建日志。")
            sys.exit(1)
    print("[启动器] 前端已就绪")
    try:
        _clear_stale_browser_cache(DESKTOP_PROFILE_ROOT, _frontend_cache_version())
    except (OSError, RuntimeError, ValueError) as cache_exc:
        print(f"[启动器] 浏览器缓存刷新跳过: {cache_exc}")

    # Start uvicorn in daemon thread (IN-PROCESS — single process)
    host = "127.0.0.1"

    # 0.1.8.1 port-bridge: persist the chosen port so the dev frontend
    # (vite proxy) and the installed shell window converge on the same
    # value. Best-effort — never blocks startup.
    try:
        from literature_assistant.core.python_adapter_server import write_api_port_file
        from literature_assistant.core.runtime_descriptor import (
            build_desktop_runtime_descriptor,
            delete_desktop_runtime_closed_marker,
            write_desktop_runtime_descriptor,
        )

        delete_desktop_runtime_closed_marker()
        write_api_port_file(port)
        write_desktop_runtime_descriptor(
            build_desktop_runtime_descriptor(
                host=host,
                port=port,
                process_kind="desktop",
                launched_by="start_desktop.py",
                ready=False,
                window_title=WINDOW_TITLE,
            )
        )
    except Exception as _port_exc:
        print(f"[启动器] 运行时描述符写入失败（忽略）: {_port_exc}")

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

    base_url = f"http://{host}:{port}"
    try:
        url = _build_desktop_frontend_url(
            base_url,
            os.environ.get("LITERATURE_ASSISTANT_DESKTOP_INITIAL_PATH"),
        )
    except ValueError as initial_path_exc:
        print(f"[启动器] 初始路径无效，已回退首页: {initial_path_exc}")
        url = base_url
    try:
        from literature_assistant.core.runtime_descriptor import refresh_desktop_runtime_descriptor

        refresh_desktop_runtime_descriptor(ready=True)
    except Exception as _descriptor_exc:
        print(f"[启动器] 运行时描述符刷新失败（忽略）: {_descriptor_exc}")
    print(f"[启动器] 后端就绪: {base_url}")
    print(f"[启动器] LITERATURE_ASSISTANT_BASE_URL={base_url}")
    if url != base_url:
        print(f"[启动器] 桌面初始路径: {url}")
    print("[启动器] 如果智能体找不到文献助手端口，请把上一行完整贴给智能体")

    # Open pywebview native window (blocks main thread)
    api = NativeApi()
    geometry = _desktop_window_geometry()
    window_kwargs: dict[str, object] = {
        "width": geometry.width,
        "height": geometry.height,
        "frameless": False,
        "text_select": True,
        "js_api": api,
        "background_color": LIGHT_APP_BACKGROUND,
    }
    if geometry.x is not None and geometry.y is not None:
        window_kwargs["x"] = geometry.x
        window_kwargs["y"] = geometry.y
        print(f"[启动器] 桌面窗口位置: {geometry.width}x{geometry.height}+{geometry.x}+{geometry.y}")
    else:
        print(f"[启动器] 桌面窗口尺寸: {geometry.width}x{geometry.height}")
    window = webview.create_window(
        WINDOW_TITLE, url=url,
        **window_kwargs,
    )
    if window is not None:
        window.events.before_show += _apply_windows_titlebar_colors
    print("[启动器] 桌面窗口已打开，关闭窗口将退出程序")
    try:
        webview.start(
            func=_install_reload_hotkeys if window is not None else None,
            args=(window,) if window is not None else None,
            debug=bool(os.environ.get("LITERATURE_ASSISTANT_DEBUG")),
            private_mode=False,
            storage_path=str(DESKTOP_PROFILE_ROOT),
        )
    finally:
        try:
            from literature_assistant.core.runtime_descriptor import (
                delete_desktop_runtime_descriptor,
                write_desktop_runtime_closed_marker,
            )

            write_desktop_runtime_closed_marker(reason="window_closed")
            delete_desktop_runtime_descriptor()
        except Exception:
            pass

    # Window closed → daemon threads auto-terminate with process exit
    print("[启动器] 窗口已关闭，退出")


if __name__ == "__main__":
    main()
