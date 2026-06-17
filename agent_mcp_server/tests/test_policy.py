"""Tests for PathPolicy."""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from lit_assistant_mcp.policy import PathPolicy


@pytest.fixture
def temp_repo():
    """Create a temporary repo structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)

        # Create structure
        (repo / ".env").write_text("SECRET=abc123")
        (repo / ".ENV").write_text("SECRET=xyz789")
        (repo / "workspace_artifacts/runtime_state").mkdir(parents=True)
        (repo / "workspace_artifacts/runtime_state/secrets.json").write_text("{}")
        (repo / "literature_assistant/core/routers").mkdir(parents=True)
        (repo / "literature_assistant/core/routers/chat_router.py").write_text("# router")

        yield repo


def test_path_traversal_blocked_unix_style(temp_repo):
    """Test that ../../.env is blocked."""
    policy = PathPolicy(
        repo_root=temp_repo,
        allowed_roots=["literature_assistant/"],
        denied_patterns=["**/.env*"],
    )

    allowed, reason = policy.is_allowed("literature_assistant/../../.env")
    assert not allowed
    assert "denied pattern" in reason.lower() or "outside" in reason.lower()


def test_path_traversal_blocked_windows_style(temp_repo):
    """Test that ..\\..\\.env is blocked (Windows)."""
    policy = PathPolicy(
        repo_root=temp_repo,
        allowed_roots=["literature_assistant/"],
        denied_patterns=["**/.env*"],
    )

    allowed, reason = policy.is_allowed("literature_assistant\\..\\../.env")
    assert not allowed
    assert "denied pattern" in reason.lower() or "outside" in reason.lower()


def test_absolute_env_path_blocked(temp_repo):
    """Test that absolute path to .env is blocked."""
    policy = PathPolicy(
        repo_root=temp_repo,
        allowed_roots=["literature_assistant/"],
        denied_patterns=["**/.env*"],
    )

    env_path = temp_repo / ".env"
    allowed, reason = policy.is_allowed(str(env_path))
    assert not allowed


def test_uppercase_env_blocked_windows(temp_repo):
    """Test that .ENV (uppercase) is blocked on Windows."""
    policy = PathPolicy(
        repo_root=temp_repo,
        allowed_roots=["literature_assistant/"],
        denied_patterns=["**/.env*"],
    )

    # On Windows, case-insensitive; on Unix, treat as separate
    env_upper = temp_repo / ".ENV"
    allowed, reason = policy.is_allowed(str(env_upper))
    assert not allowed


def test_nested_traversal_blocked(temp_repo):
    """Test that workspace_artifacts/runtime_state/../../../.env is blocked."""
    policy = PathPolicy(
        repo_root=temp_repo,
        allowed_roots=["workspace_artifacts/"],
        denied_patterns=["**/.env*", "workspace_artifacts/runtime_state/**"],
    )

    allowed, reason = policy.is_allowed(
        "workspace_artifacts/runtime_state/../../../.env"
    )
    assert not allowed


def test_symlink_to_denied_path_blocked(temp_repo):
    """Test that symlink pointing to .env is blocked."""
    policy = PathPolicy(
        repo_root=temp_repo,
        allowed_roots=["literature_assistant/"],
        denied_patterns=["**/.env*"],
    )

    # Create symlink (skip on Windows if no admin rights)
    try:
        symlink = temp_repo / "literature_assistant/core/link_to_env"
        symlink.symlink_to(temp_repo / ".env")

        allowed, reason = policy.is_allowed(str(symlink))
        assert not allowed
        assert "denied pattern" in reason.lower()
    except OSError:
        pytest.skip("Symlink creation requires elevated privileges on Windows")


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior only")
def test_junction_to_denied_directory_blocked(temp_repo):
    """Test that a junction pointing to denied runtime state is blocked."""
    policy = PathPolicy(
        repo_root=temp_repo,
        allowed_roots=["literature_assistant/"],
        denied_patterns=["workspace_artifacts/runtime_state/**"],
    )

    junction = temp_repo / "literature_assistant/core/runtime_link"
    target = temp_repo / "workspace_artifacts/runtime_state"

    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"Junction creation failed: {result.stderr or result.stdout}")

    try:
        allowed, reason = policy.is_allowed(
            "literature_assistant/core/runtime_link/secrets.json"
        )
        assert not allowed
        assert "denied pattern" in reason.lower()
    finally:
        try:
            junction.rmdir()
        except OSError:
            pass


def test_allowed_file_passes(temp_repo):
    """Test that allowed file passes all checks."""
    policy = PathPolicy(
        repo_root=temp_repo,
        allowed_roots=["literature_assistant/"],
        denied_patterns=["**/.env*", "workspace_artifacts/runtime_state/**"],
    )

    allowed, reason = policy.is_allowed(
        "literature_assistant/core/routers/chat_router.py"
    )
    assert allowed
    assert reason == "allowed"
    assert len(policy.touched_paths) == 1
