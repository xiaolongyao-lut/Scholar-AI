"""Explicit debug backend launcher for stdio MCP startup."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

import httpx


DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
DEFAULT_STARTUP_TIMEOUT_SEC = 45.0
_CAPABILITY_FILE_ENV = "LITASSIST_API_CAPABILITY_FILE"


def ensure_backend_running(
    repo_root: Path,
    base_url: str = DEFAULT_BACKEND_URL,
    startup_timeout_sec: float = DEFAULT_STARTUP_TIMEOUT_SEC,
    python_executable: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Ensure a debug local HTTP backend exists for MCP runtime tools.

    Args:
        repo_root: Repository root containing ``AI_WORKSPACE_GUIDE.md``.
        base_url: Backend base URL; only loopback HTTP URLs are auto-started.
        startup_timeout_sec: Maximum wait for the health endpoint.
        python_executable: Python used to launch Uvicorn when needed.
        env: Process environment inherited by the backend.

    Returns:
        ``True`` when a backend is reachable, ``False`` when startup is skipped
        or cannot complete within the caller's startup budget.

    This helper is intentionally headless and should only be called when the
    wrapper has opted into ``LITASSIST_MCP_ALLOW_HEADLESS_AUTOSTART=1``. Default
    MCP startup should use ``runtime_attach`` so the user-visible desktop app is
    the runtime owner.
    """
    repo_root = repo_root.expanduser().resolve()
    if not (repo_root / "AI_WORKSPACE_GUIDE.md").is_file():
        raise ValueError("repo_root must point at the Literature Assistant repository root")
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("base_url must be a non-empty string")
    if startup_timeout_sec <= 0:
        raise ValueError("startup_timeout_sec must be positive")

    cleaned_base_url = base_url.rstrip("/")
    if not _is_loopback_http_url(cleaned_base_url):
        return _health_ok(cleaned_base_url, timeout_sec=2.0)
    if _health_ok(cleaned_base_url, timeout_sec=2.0):
        return True

    parsed = urlparse(cleaned_base_url)
    if parsed.scheme != "http":
        return False
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    launch_env = dict(os.environ if env is None else env)
    launch_env.setdefault("LITERATURE_ASSISTANT_REPO_ROOT", str(repo_root))
    launch_env.setdefault(
        "LITERATURE_ASSISTANT_RUNTIME_STATE_ROOT",
        str(repo_root / "workspace_artifacts" / "runtime_state"),
    )
    capability_file = _isolated_capability_file(repo_root, cleaned_base_url)
    if capability_file is not None:
        launch_env.setdefault(_CAPABILITY_FILE_ENV, str(capability_file))
    log_root = repo_root / "workspace_artifacts" / "runtime_state" / "mcp_backend"
    log_root.mkdir(parents=True, exist_ok=True)
    stdout_path = log_root / "uvicorn.stdout.log"
    stderr_path = log_root / "uvicorn.stderr.log"
    executable = _backend_python_executable(python_executable or _default_python_executable(repo_root))

    with stdout_path.open("ab") as stdout_file, stderr_path.open("ab") as stderr_file:
        subprocess.Popen(
            [
                executable,
                "-m",
                "uvicorn",
                "literature_assistant.core.python_adapter_server:app",
                "--host",
                host,
                "--port",
                str(port),
            ],
            cwd=repo_root,
            env=launch_env,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            creationflags=_creation_flags(),
            close_fds=False,
        )

    deadline = time.monotonic() + startup_timeout_sec
    while time.monotonic() < deadline:
        if _health_ok(cleaned_base_url, timeout_sec=2.0):
            return True
        time.sleep(0.5)
    return False


def main(argv: list[str] | None = None) -> int:
    """Run a silent backend readiness check for wrapper scripts."""
    parser = argparse.ArgumentParser(description="Ensure Literature Assistant backend is running.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--base-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--startup-timeout-sec", type=float, default=DEFAULT_STARTUP_TIMEOUT_SEC)
    args = parser.parse_args(argv)
    try:
        return 0 if ensure_backend_running(
            repo_root=Path(args.repo_root),
            base_url=args.base_url,
            startup_timeout_sec=args.startup_timeout_sec,
            python_executable=sys.executable,
        ) else 1
    except Exception:
        return 1


def _health_ok(base_url: str, timeout_sec: float) -> bool:
    """Return whether the backend health endpoint answers successfully."""
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/health", timeout=timeout_sec)
        response.raise_for_status()
    except httpx.HTTPError:
        return False
    return True


def _is_loopback_http_url(value: str) -> bool:
    """Return whether a URL targets the same-machine HTTP backend."""
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and hostname in {"localhost", "127.0.0.1", "::1"}


def _default_python_executable(repo_root: Path) -> Path:
    """Return the repository venv interpreter used by canonical commands."""
    if os.name == "nt":
        return repo_root / ".venv-1" / "Scripts" / "python.exe"
    return repo_root / ".venv-1" / "bin" / "python"


def _backend_python_executable(executable: str | Path) -> str:
    """Return a non-console Python executable for hidden backend autostart."""
    executable_path = Path(executable)
    if os.name != "nt":
        return str(executable)
    if executable_path.name.lower() != "python.exe":
        return str(executable)
    gui_executable = executable_path.with_name("pythonw.exe")
    if gui_executable.is_file():
        return str(gui_executable)
    return str(executable)


def _isolated_capability_file(repo_root: Path, base_url: str) -> Path | None:
    """Return a port-specific token file for non-default loopback backends."""
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    if parsed.scheme == "http" and hostname in {"localhost", "127.0.0.1", "::1"} and port in {None, 8000}:
        return None
    if not _is_loopback_http_url(base_url):
        return None
    effective_port = port or (443 if parsed.scheme == "https" else 80)
    safe_host = hostname.replace(":", "_").strip("_") or "loopback"
    return repo_root / "workspace_artifacts" / "runtime_state" / "api-capabilities" / f"{safe_host}-{effective_port}.json"


def _creation_flags() -> int:
    """Return process flags that keep helper startup invisible on Windows."""
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
