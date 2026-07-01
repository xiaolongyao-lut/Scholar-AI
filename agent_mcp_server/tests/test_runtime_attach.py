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
    _terminal_python_executable,
    _visible_terminal_launch_command,
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


def _public_repo_root(tmp_path: Path) -> Path:
    """Create a public source-tree marker without local-only workspace guides."""

    root = tmp_path / "public-repo"
    root.mkdir()
    (root / "SOURCE_RELEASE_POLICY.md").write_text("# policy\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = \"scholar-ai\"\n", encoding="utf-8")
    (root / "agent_mcp_server").mkdir()
    (root / "literature_assistant").mkdir()
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
    assert launch.call_args.kwargs["terminal_visible"] is False


def test_public_source_tree_anchor_can_attach_without_launch(tmp_path: Path) -> None:
    """Public source archives should pass root validation for attach-only MCP."""

    repo_root = _public_repo_root(tmp_path)
    attached = ensure_desktop_runtime_attached(
        repo_root,
        startup_timeout_sec=1.0,
        env={},
        launch_when_missing=False,
    )

    assert attached is None


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
    assert launch.call_args.kwargs["terminal_visible"] is False


def test_launch_desktop_runtime_runs_start_desktop(tmp_path: Path) -> None:
    """Hidden desktop launch should target start_desktop.py without a terminal wrapper."""

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


def test_launch_desktop_runtime_visible_terminal_uses_powershell_wrapper(tmp_path: Path) -> None:
    """Explicit launch requests should open a terminal that runs start_desktop.py."""

    repo_root = _repo_root(tmp_path)
    with patch("lit_assistant_mcp.runtime_attach.os.name", "nt"), patch(
        "lit_assistant_mcp.runtime_attach.subprocess.Popen"
    ) as popen:
        launch_desktop_runtime(
            repo_root=repo_root,
            python_executable=str(repo_root / ".venv-1" / "Scripts" / "python.exe"),
            env={},
            terminal_visible=True,
        )

    command = popen.call_args.args[0]
    assert command[:6] == ["powershell.exe", "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
    assert "Set-Location -LiteralPath" in command[-1]
    assert str(repo_root) in command[-1]
    assert str(repo_root / "start_desktop.py") in command[-1]
    assert popen.call_args.kwargs["cwd"] == repo_root
    assert popen.call_args.kwargs["env"]["LITERATURE_ASSISTANT_REPO_ROOT"] == str(repo_root)
    assert "stdin" not in popen.call_args.kwargs
    assert "stdout" not in popen.call_args.kwargs
    assert "stderr" not in popen.call_args.kwargs


def test_windows_hidden_desktop_autostart_does_not_request_console() -> None:
    """Default MCP autostart must stay terminal-free."""

    with patch("lit_assistant_mcp.runtime_attach.os.name", "nt"), patch(
        "lit_assistant_mcp.runtime_attach.subprocess.CREATE_NO_WINDOW",
        0x08000000,
        create=True,
    ), patch(
        "lit_assistant_mcp.runtime_attach.subprocess.CREATE_NEW_CONSOLE",
        0x00000010,
        create=True,
    ):
        flags = _creation_flags(terminal_visible=False)

    assert flags & 0x08000000
    assert not flags & 0x00000010


def test_windows_visible_terminal_launch_requests_console() -> None:
    """Explicit launch requests should allocate a Windows console."""

    with patch("lit_assistant_mcp.runtime_attach.os.name", "nt"), patch(
        "lit_assistant_mcp.runtime_attach.subprocess.CREATE_NO_WINDOW",
        0x08000000,
        create=True,
    ), patch(
        "lit_assistant_mcp.runtime_attach.subprocess.CREATE_NEW_CONSOLE",
        0x00000010,
        create=True,
    ):
        flags = _creation_flags(terminal_visible=True)

    assert flags & 0x00000010
    assert not flags & 0x08000000


def test_windows_desktop_autostart_prefers_pythonw(tmp_path: Path) -> None:
    """GUI Python avoids allocating a console for pywebview autostart."""

    python_exe = tmp_path / "python.exe"
    pythonw_exe = tmp_path / "pythonw.exe"
    python_exe.write_text("", encoding="utf-8")
    pythonw_exe.write_text("", encoding="utf-8")

    with patch("lit_assistant_mcp.runtime_attach.os.name", "nt"):
        executable = _desktop_python_executable(python_exe)

    assert executable == str(pythonw_exe)


def test_windows_visible_terminal_launch_prefers_python(tmp_path: Path) -> None:
    """Visible terminal launches must not use pythonw.exe."""

    python_exe = tmp_path / "python.exe"
    pythonw_exe = tmp_path / "pythonw.exe"
    python_exe.write_text("", encoding="utf-8")
    pythonw_exe.write_text("", encoding="utf-8")

    with patch("lit_assistant_mcp.runtime_attach.os.name", "nt"):
        executable = _terminal_python_executable(pythonw_exe)

    assert executable == str(python_exe)


def test_visible_terminal_launch_command_quotes_powershell_paths(tmp_path: Path) -> None:
    """PowerShell command should preserve repository paths with spaces or quotes."""

    quoted_parent = tmp_path / "repo with ' quote"
    quoted_parent.mkdir()
    repo_root = _repo_root(quoted_parent)
    python_exe = repo_root / ".venv-1" / "Scripts" / "python.exe"
    with patch("lit_assistant_mcp.runtime_attach.os.name", "nt"):
        command = _visible_terminal_launch_command(
            repo_root=repo_root,
            executable=str(python_exe),
            start_script=repo_root / "start_desktop.py",
        )

    assert command[:6] == ["powershell.exe", "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
    assert "repo with '' quote" in command[-1]
    assert "start_desktop.py" in command[-1]
