"""Attach MCP startup to the visible Literature Assistant desktop runtime."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx

from .repo_root import validate_repo_root


DESKTOP_RUNTIME_FILENAME = "desktop-runtime.json"
DESKTOP_RUNTIME_CLOSED_FILENAME = "desktop-runtime-closed.json"
DEFAULT_STARTUP_TIMEOUT_SEC = 60.0
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DesktopRuntimeAttachment:
    """Validated desktop runtime attachment data."""

    base_url: str
    capability_file: Path | None
    descriptor_file: Path
    pid: int
    process_kind: str


def ensure_desktop_runtime_attached(
    repo_root: Path,
    startup_timeout_sec: float = DEFAULT_STARTUP_TIMEOUT_SEC,
    python_executable: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    launch_when_missing: bool = True,
) -> DesktopRuntimeAttachment | None:
    """Attach to a visible desktop runtime, launching it when allowed.

    Args:
        repo_root: Private checkout or public source-tree repository root.
        startup_timeout_sec: Maximum time to wait for descriptor readiness.
        python_executable: Interpreter used to launch ``start_desktop.py``.
        env: Environment visible to the launched desktop process.
        launch_when_missing: Whether to open the desktop UI if no descriptor is
            currently valid.

    Returns:
        A validated attachment or ``None`` when attachment is unavailable.
    """

    resolved_root = validate_repo_root(repo_root)
    if startup_timeout_sec <= 0:
        raise ValueError("startup_timeout_sec must be positive")

    descriptor_file = _descriptor_file(resolved_root, env=env)
    existing = read_valid_desktop_runtime(descriptor_file)
    if existing is not None:
        return existing
    if desktop_runtime_was_deliberately_closed(resolved_root, env=env) and not _force_desktop_launch(env):
        return None
    if not launch_when_missing:
        return None

    launch_desktop_runtime(
        repo_root=resolved_root,
        python_executable=python_executable,
        env=env,
    )
    deadline = time.monotonic() + startup_timeout_sec
    while time.monotonic() < deadline:
        attached = read_valid_desktop_runtime(descriptor_file)
        if attached is not None:
            return attached
        time.sleep(0.5)
    return None


def desktop_runtime_was_deliberately_closed(repo_root: Path, env: Mapping[str, str] | None = None) -> bool:
    """Return whether a previous visible runtime was closed by the user.

    Args:
        repo_root: Repository root containing the runtime-state directory.

    Why:
        MCP hosts can restart stdio servers on demand. A close marker prevents
        that host lifecycle from reopening the user's desktop app after they
        intentionally dismissed it.
    """

    marker = _closed_marker_file(repo_root.expanduser().resolve(), env=env)
    if not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    if not isinstance(payload, dict):
        return True
    return payload.get("schema_version") == SCHEMA_VERSION


def read_valid_desktop_runtime(descriptor_file: Path) -> DesktopRuntimeAttachment | None:
    """Read and validate a desktop runtime descriptor."""

    if not descriptor_file.is_file():
        return None
    try:
        payload = json.loads(descriptor_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != SCHEMA_VERSION:
        return None
    if payload.get("process_kind") != "desktop":
        return None
    if payload.get("ready") is not True:
        return None

    base_url = str(payload.get("base_url") or "").rstrip("/")
    if not _is_loopback_http_url(base_url):
        return None
    pid = _coerce_pid(payload.get("pid"))
    if pid is None or not _pid_exists(pid):
        return None

    capability_file = _coerce_optional_path(payload.get("capability_file"))
    if capability_file is not None and not capability_file.is_file():
        return None
    if not _health_ok(base_url, capability_file, timeout_sec=2.0):
        return None
    return DesktopRuntimeAttachment(
        base_url=base_url,
        capability_file=capability_file,
        descriptor_file=descriptor_file,
        pid=pid,
        process_kind="desktop",
    )


def launch_desktop_runtime(
    *,
    repo_root: Path,
    python_executable: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    """Launch the source desktop app without opening an extra terminal window."""

    start_script = repo_root / "start_desktop.py"
    if not start_script.is_file():
        raise ValueError("start_desktop.py not found under repo_root")
    launch_env = dict(os.environ if env is None else env)
    launch_env.setdefault("LITERATURE_ASSISTANT_REPO_ROOT", str(repo_root))
    executable = _desktop_python_executable(python_executable or _default_python_executable(repo_root))
    command = _desktop_launch_command(executable=executable, start_script=start_script)
    stdout_path, stderr_path = _desktop_autostart_log_paths(repo_root)
    with stdout_path.open("ab") as stdout_file, stderr_path.open("ab") as stderr_file:
        subprocess.Popen(
            command,
            cwd=repo_root,
            env=launch_env,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            creationflags=_creation_flags(visible=True),
            close_fds=False,
        )


def main(argv: list[str] | None = None) -> int:
    """Attach to or launch the visible desktop runtime for wrapper scripts."""

    parser = argparse.ArgumentParser(description="Attach MCP to the visible Literature Assistant desktop runtime.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--startup-timeout-sec", type=float, default=DEFAULT_STARTUP_TIMEOUT_SEC)
    parser.add_argument("--print-env", action="store_true")
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--force-launch", action="store_true")
    args = parser.parse_args(argv)
    try:
        env = dict(os.environ)
        if args.force_launch:
            env["LITASSIST_MCP_FORCE_DESKTOP_AUTOSTART"] = "1"
        attached = ensure_desktop_runtime_attached(
            repo_root=Path(args.repo_root),
            startup_timeout_sec=args.startup_timeout_sec,
            python_executable=sys.executable,
            env=env,
            launch_when_missing=not args.no_launch,
        )
    except Exception:
        return 1
    if attached is None:
        return 1
    if args.print_env:
        payload = {
            "LITERATURE_ASSISTANT_BASE_URL": attached.base_url,
            "LITASSIST_API_CAPABILITY_FILE": str(attached.capability_file) if attached.capability_file else "",
            "LITASSIST_DESKTOP_RUNTIME_FILE": str(attached.descriptor_file),
        }
        print(json.dumps(payload, ensure_ascii=False))
    return 0


def _descriptor_file(repo_root: Path, env: Mapping[str, str] | None = None) -> Path:
    source_env = os.environ if env is None else env
    runtime_root = source_env.get("LITERATURE_ASSISTANT_RUNTIME_STATE_ROOT", "").strip()
    if runtime_root:
        return Path(runtime_root).expanduser().resolve() / DESKTOP_RUNTIME_FILENAME
    return repo_root / "workspace_artifacts" / "runtime_state" / DESKTOP_RUNTIME_FILENAME


def _closed_marker_file(repo_root: Path, env: Mapping[str, str] | None = None) -> Path:
    source_env = os.environ if env is None else env
    runtime_root = source_env.get("LITERATURE_ASSISTANT_RUNTIME_STATE_ROOT", "").strip()
    if runtime_root:
        return Path(runtime_root).expanduser().resolve() / DESKTOP_RUNTIME_CLOSED_FILENAME
    return repo_root / "workspace_artifacts" / "runtime_state" / DESKTOP_RUNTIME_CLOSED_FILENAME


def _force_desktop_launch(env: Mapping[str, str] | None) -> bool:
    source_env = os.environ if env is None else env
    value = source_env.get("LITASSIST_MCP_FORCE_DESKTOP_AUTOSTART", "")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _desktop_launch_command(*, executable: str, start_script: Path) -> list[str]:
    """Return the direct desktop launch command.

    Why:
        Windows ``cmd.exe /k`` leaves a terminal window behind for every MCP
        autostart. The source desktop app already publishes runtime descriptors,
        and this module writes stdout/stderr to local log files instead.
    """

    if not isinstance(executable, str) or not executable.strip():
        raise ValueError("executable must be a non-empty string")
    if not isinstance(start_script, Path) or not start_script.is_file():
        raise ValueError("start_script must be an existing file")
    return [executable, str(start_script)]


def _desktop_python_executable(executable: str | Path) -> str:
    """Return the GUI Python executable for desktop autostart when available."""

    executable_path = Path(executable)
    if os.name != "nt":
        return str(executable)
    if executable_path.name.lower() != "python.exe":
        return str(executable)
    gui_executable = executable_path.with_name("pythonw.exe")
    if gui_executable.is_file():
        return str(gui_executable)
    return str(executable)


def _desktop_autostart_log_paths(repo_root: Path) -> tuple[Path, Path]:
    """Return local log files used when MCP autostarts the desktop app."""

    log_root = repo_root / "workspace_artifacts" / "runtime_state" / "desktop_autostart"
    log_root.mkdir(parents=True, exist_ok=True)
    return log_root / "start_desktop.stdout.log", log_root / "start_desktop.stderr.log"


def _health_ok(base_url: str, capability_file: Path | None, timeout_sec: float) -> bool:
    headers: dict[str, str] = {}
    if capability_file is not None:
        headers.update(_capability_headers(capability_file))
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/health", headers=headers, timeout=timeout_sec)
        response.raise_for_status()
    except httpx.HTTPError:
        return False
    return True


def _capability_headers(capability_file: Path) -> dict[str, str]:
    try:
        payload = json.loads(capability_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    header = str(payload.get("header") or "").strip()
    token = str(payload.get("token") or "").strip()
    if not header or not token:
        return {}
    return {header: token}


def _is_loopback_http_url(value: str) -> bool:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and hostname in {"localhost", "127.0.0.1", "::1"}


def _coerce_pid(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _coerce_optional_path(value: Any) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return Path(text).expanduser().resolve()


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _default_python_executable(repo_root: Path) -> Path:
    if os.name == "nt":
        return repo_root / ".venv-1" / "Scripts" / "python.exe"
    return repo_root / ".venv-1" / "bin" / "python"


def _creation_flags(*, visible: bool) -> int:
    """Return process flags for desktop autostart.

    Args:
        visible: Whether the pywebview application window should be user-visible.

    Why:
        ``visible`` means the native ``文献助手`` window is allowed to appear,
        not that Windows should allocate a console. The desktop app is a GUI
        acceptance surface; logs belong in ``workspace_artifacts``.
    """

    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
