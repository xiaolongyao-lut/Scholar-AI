"""Tests for desktop-first MCP runtime attachment."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import Mock, patch

from lit_assistant_mcp.runtime_attach import (
    DESKTOP_RUNTIME_CLOSED_FILENAME,
    _creation_flags,
    _desktop_python_executable,
    ensure_desktop_runtime_attached,
    launch_desktop_runtime,
    read_valid_desktop_runtime,
)


def _repo_root(tmp_path: Path) -> Path:
    """Create a minimal Literature Assistant repository marker."""

    root = tmp_path / "repo"
    root.mkdir()
    (root / "AI_WORKSPACE_GUIDE.md").write_text("# guide\n", encoding="utf-8")
    (root / "start_desktop.py").write_text("print('desktop')\n", encoding="utf-8")
    return root


def _write_descriptor(repo_root: Path, *, pid: int | None = None) -> Path:
    """Write a descriptor plus matching capability file for attach tests."""

    runtime_root = repo_root / "workspace_artifacts" / "runtime_state"
    runtime_root.mkdir(parents=True)
    capability_file = runtime_root / "api-capability.json"
    capability_file.write_text(
        json.dumps({"header": "X-LitAssist-Capability", "token": "secret"}),
        encoding="utf-8",
    )
    descriptor_file = runtime_root / "desktop-runtime.json"
    descriptor_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pid": pid or os.getpid(),
                "process_kind": "desktop",
                "base_url": "http://127.0.0.1:8123",
                "ready": True,
                "capability_file": str(capability_file),
            }
        ),
        encoding="utf-8",
    )
    return descriptor_file


def test_read_valid_desktop_runtime_uses_descriptor_and_capability(tmp_path: Path) -> None:
    """A healthy desktop descriptor should become the MCP base URL."""

    repo_root = _repo_root(tmp_path)
    descriptor_file = _write_descriptor(repo_root)
    response = Mock()
    response.raise_for_status.return_value = None
    with patch("lit_assistant_mcp.runtime_attach.httpx.get", return_value=response) as get:
        attached = read_valid_desktop_runtime(descriptor_file)

    assert attached is not None
    assert attached.base_url == "http://127.0.0.1:8123"
    assert attached.capability_file is not None
    assert attached.capability_file.name == "api-capability.json"
    assert get.call_args.kwargs["headers"] == {"X-LitAssist-Capability": "secret"}


def test_stale_pid_descriptor_is_rejected(tmp_path: Path) -> None:
    """Stale descriptors must not attach MCP to a dead desktop runtime."""

    repo_root = _repo_root(tmp_path)
    descriptor_file = _write_descriptor(repo_root, pid=999_999_999)

    assert read_valid_desktop_runtime(descriptor_file) is None


def test_missing_descriptor_launches_desktop_when_allowed(tmp_path: Path) -> None:
    """Default attach path may open the visible desktop UI before user closes it."""

    repo_root = _repo_root(tmp_path)
    env = {"LITERATURE_ASSISTANT_RUNTIME_STATE_ROOT": str(repo_root / "workspace_artifacts" / "runtime_state")}
    with patch("lit_assistant_mcp.runtime_attach.launch_desktop_runtime") as launch, patch(
        "lit_assistant_mcp.runtime_attach.read_valid_desktop_runtime",
        side_effect=[None, None, None],
    ):
        attached = ensure_desktop_runtime_attached(
            repo_root,
            startup_timeout_sec=0.01,
            python_executable="python-test",
            env=env,
        )

    assert attached is None
    launch.assert_called_once()


def test_closed_marker_blocks_relaunch_after_user_close(tmp_path: Path) -> None:
    """A deliberate user close should suppress MCP-driven relaunch."""

    repo_root = _repo_root(tmp_path)
    runtime_root = repo_root / "workspace_artifacts" / "runtime_state"
    runtime_root.mkdir(parents=True)
    (runtime_root / DESKTOP_RUNTIME_CLOSED_FILENAME).write_text(
        json.dumps({"schema_version": 1, "reason": "window_closed"}),
        encoding="utf-8",
    )
    with patch("lit_assistant_mcp.runtime_attach.launch_desktop_runtime") as launch:
        attached = ensure_desktop_runtime_attached(
            repo_root,
            startup_timeout_sec=0.01,
            python_executable="python-test",
            env={},
        )

    assert attached is None
    launch.assert_not_called()


def test_force_launch_ignores_closed_marker(tmp_path: Path) -> None:
    """Codex-triggered explicit launch can reopen the desktop after a close."""

    repo_root = _repo_root(tmp_path)
    runtime_root = repo_root / "workspace_artifacts" / "runtime_state"
    runtime_root.mkdir(parents=True)
    (runtime_root / DESKTOP_RUNTIME_CLOSED_FILENAME).write_text(
        json.dumps({"schema_version": 1, "reason": "window_closed"}),
        encoding="utf-8",
    )
    with patch("lit_assistant_mcp.runtime_attach.launch_desktop_runtime") as launch, patch(
        "lit_assistant_mcp.runtime_attach.read_valid_desktop_runtime",
        side_effect=[None, None, None],
    ):
        attached = ensure_desktop_runtime_attached(
            repo_root,
            startup_timeout_sec=0.01,
            python_executable="python-test",
            env={"LITASSIST_MCP_FORCE_DESKTOP_AUTOSTART": "1"},
        )

    assert attached is None
    launch.assert_called_once()


def test_launch_desktop_runtime_runs_start_desktop(tmp_path: Path) -> None:
    """Desktop launch should target start_desktop.py without a terminal wrapper."""

    repo_root = _repo_root(tmp_path)
    with patch("lit_assistant_mcp.runtime_attach.subprocess.Popen") as popen:
        launch_desktop_runtime(repo_root=repo_root, python_executable="python-test", env={})

    command = popen.call_args.args[0]
    assert command == ["python-test", str(repo_root / "start_desktop.py")]
    assert popen.call_args.kwargs["cwd"] == repo_root
    assert popen.call_args.kwargs["env"]["LITERATURE_ASSISTANT_REPO_ROOT"] == str(repo_root)
    assert popen.call_args.kwargs["stdin"] is not None
    assert "desktop_autostart" in str(popen.call_args.kwargs["stdout"].name)
    assert "desktop_autostart" in str(popen.call_args.kwargs["stderr"].name)


def test_windows_desktop_autostart_does_not_request_console() -> None:
    """A visible pywebview window must not imply a visible Windows terminal."""

    with patch("lit_assistant_mcp.runtime_attach.os.name", "nt"):
        flags = _creation_flags(visible=True)

    assert flags & int(getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0))
    assert not flags & int(getattr(__import__("subprocess"), "CREATE_NEW_CONSOLE", 0))


def test_windows_desktop_autostart_prefers_pythonw(tmp_path: Path) -> None:
    """GUI Python avoids allocating a console for pywebview autostart."""

    python_exe = tmp_path / "python.exe"
    pythonw_exe = tmp_path / "pythonw.exe"
    python_exe.write_text("", encoding="utf-8")
    pythonw_exe.write_text("", encoding="utf-8")

    with patch("lit_assistant_mcp.runtime_attach.os.name", "nt"):
        executable = _desktop_python_executable(python_exe)

    assert executable == str(pythonw_exe)
