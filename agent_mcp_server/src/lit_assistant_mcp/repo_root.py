"""Repository-root validation helpers for private and public source trees."""

from __future__ import annotations

from pathlib import Path


def is_repo_root(candidate: Path) -> bool:
    """Return True when a path has private or public Scholar AI anchors.

    Args:
        candidate: Path that may be the repository root.

    Returns:
        Whether the path can safely act as the local source checkout root.
    """

    if (candidate / "AI_WORKSPACE_GUIDE.md").is_file():
        return True
    return (
        (candidate / "SOURCE_RELEASE_POLICY.md").is_file()
        and (candidate / "pyproject.toml").is_file()
        and (candidate / "agent_mcp_server").is_dir()
        and (candidate / "literature_assistant").is_dir()
    )


def validate_repo_root(repo_root: Path) -> Path:
    """Return a resolved root or raise when anchors are missing.

    Args:
        repo_root: Candidate repository root.

    Returns:
        Resolved repository root.

    Raises:
        ValueError: If the path is not a Scholar AI private or public source tree.
    """

    resolved_root = repo_root.expanduser().resolve()
    if not is_repo_root(resolved_root):
        raise ValueError("repo_root must point at the Scholar AI repository root")
    return resolved_root
