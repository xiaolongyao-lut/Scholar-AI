"""Tests for silent backend readiness bootstrap."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest

from lit_assistant_mcp.backend_launcher import ensure_backend_running


def _repo_root(tmp_path: Path) -> Path:
    """Create a minimal repository marker for launcher validation."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "AI_WORKSPACE_GUIDE.md").write_text("# guide\n", encoding="utf-8")
    return root


def test_existing_health_skips_process_start(tmp_path: Path) -> None:
    """Reachable backends should not spawn another Uvicorn process."""
    repo_root = _repo_root(tmp_path)
    response = Mock()
    response.raise_for_status.return_value = None
    with patch("lit_assistant_mcp.backend_launcher.httpx.get", return_value=response) as get, patch(
        "lit_assistant_mcp.backend_launcher.subprocess.Popen"
    ) as popen:
        result = ensure_backend_running(repo_root, startup_timeout_sec=1.0)

    assert result is True
    assert get.call_args.args[0] == "http://127.0.0.1:8000/health"
    popen.assert_not_called()


def test_loopback_backend_is_started_when_health_missing(tmp_path: Path) -> None:
    """Missing loopback backend should be launched with the canonical ASGI entrypoint."""
    repo_root = _repo_root(tmp_path)
    response = Mock()
    response.raise_for_status.return_value = None
    side_effect = [httpx.ConnectError("offline"), response]
    with patch("lit_assistant_mcp.backend_launcher.httpx.get", side_effect=side_effect), patch(
        "lit_assistant_mcp.backend_launcher.subprocess.Popen"
    ) as popen:
        result = ensure_backend_running(
            repo_root,
            startup_timeout_sec=1.0,
            python_executable="python-test",
            env={},
        )

    assert result is True
    command = popen.call_args.args[0]
    assert command == [
        "python-test",
        "-m",
        "uvicorn",
        "literature_assistant.core.python_adapter_server:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    assert popen.call_args.kwargs["cwd"] == repo_root
    assert popen.call_args.kwargs["stdout"].name.endswith("uvicorn.stdout.log")
    assert popen.call_args.kwargs["stderr"].name.endswith("uvicorn.stderr.log")


def test_non_default_loopback_backend_uses_isolated_capability_file(tmp_path: Path) -> None:
    """Non-default ports should not overwrite the canonical 8000 capability file."""
    repo_root = _repo_root(tmp_path)
    response = Mock()
    response.raise_for_status.return_value = None
    side_effect = [httpx.ConnectError("offline"), response]
    with patch("lit_assistant_mcp.backend_launcher.httpx.get", side_effect=side_effect), patch(
        "lit_assistant_mcp.backend_launcher.subprocess.Popen"
    ) as popen:
        result = ensure_backend_running(
            repo_root,
            base_url="http://127.0.0.1:8010",
            startup_timeout_sec=1.0,
            python_executable="python-test",
            env={},
        )

    assert result is True
    child_env = popen.call_args.kwargs["env"]
    assert child_env["LITASSIST_API_CAPABILITY_FILE"].endswith(
        "workspace_artifacts\\runtime_state\\api-capabilities\\127.0.0.1-8010.json"
    ) or child_env["LITASSIST_API_CAPABILITY_FILE"].endswith(
        "workspace_artifacts/runtime_state/api-capabilities/127.0.0.1-8010.json"
    )


def test_non_loopback_backend_is_not_autostarted(tmp_path: Path) -> None:
    """Remote configured backends must never be started by a local wrapper."""
    repo_root = _repo_root(tmp_path)
    with patch("lit_assistant_mcp.backend_launcher.httpx.get", side_effect=httpx.ConnectError("offline")), patch(
        "lit_assistant_mcp.backend_launcher.subprocess.Popen"
    ) as popen:
        result = ensure_backend_running(repo_root, base_url="https://example.invalid", startup_timeout_sec=1.0)

    assert result is False
    popen.assert_not_called()


def test_invalid_repo_root_is_rejected(tmp_path: Path) -> None:
    """Launcher should fail closed when repository identity is missing."""
    with pytest.raises(ValueError, match="repo_root"):
        ensure_backend_running(tmp_path / "missing", startup_timeout_sec=1.0)


def test_startup_timeout_returns_false(tmp_path: Path) -> None:
    """Persistent startup failure should not block stdio server launch forever."""
    repo_root = _repo_root(tmp_path)
    with patch("lit_assistant_mcp.backend_launcher.httpx.get", side_effect=httpx.ConnectError("offline")), patch(
        "lit_assistant_mcp.backend_launcher.subprocess.Popen"
    ):
        result = ensure_backend_running(repo_root, startup_timeout_sec=0.01, python_executable="python-test", env={})

    assert result is False
