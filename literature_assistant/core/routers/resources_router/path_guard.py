# -*- coding: utf-8 -*-
"""Source-folder path guard for project-scoped ingest.

Shared by ``PUT /resources/project/{id}/source-folder`` (binding mode) and
``POST /resources/project/{id}/scan-folder`` (check mode). Prevents external
agents from pointing ingest at arbitrary local paths (``.env*``, ``.codex``,
AppData, credential stores) and blocks junction/symlink/reparse-point
traversal that would escape a project's bound root.

The guard is intentionally pure: no project-store or clock access. Callers
supply timestamps and read/write project metadata. This keeps it unit-testable
without a running backend.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

# winnt.h: FILE_ATTRIBUTE_REPARSE_POINT
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
# winnt.h: INVALID_FILE_ATTRIBUTES
_INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF

# Basenames that must never be a source folder or an ancestor of one.
# Matched case-insensitively against every component of the resolved real path.
# AppData is handled by ``_is_sensitive_appdata_path`` so real Windows temp
# folders stay test-compatible while credential/browser state remains blocked.
_SENSITIVE_BASENAMES = {
    ".env",
    ".git",
    ".claude",
    ".codex",
    ".copilot",
    ".squad",
    ".claude_squad",
    ".rollback_snapshots",
    ".ssh",
    ".gnupg",
    "api-capabilities",
    "browser_profile",
    "browser_profiles",
    "credentials",
    "credentialstore",
    "keyring",
    "keyrings",
    "runtime_state",
    "secrets",
    "workspace_artifacts",
}
# ``.env`` has many siblings (.env.local, .env.production, ...); cover them with
# a pattern rather than an exhaustive set.
_SENSITIVE_PATTERN = re.compile(
    r"^(?:\.env.*|\.git|\.claude|\.codex|\.copilot|\.squad|\.claude_squad)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SourceFolderBinding:
    """Resolved, validated source folder ready to persist as a project ref.

    ``real_path`` carries the absolute resolved path for backend use only; MCP
    responses must surface ``display_name`` / ``ref_id`` instead (see plan §7
    path-privacy boundary).
    """

    project_id: str
    real_path: Path
    display_name: str
    bound_at: str


def _has_reparse_point(path: Path) -> bool:
    """Return True when ``path`` is a symlink/junction/reparse point.

    Python's :func:`os.path.islink` recognizes symlinks everywhere and
    junctions on 3.12+. To also catch junctions/reparse points on older
    runtimes we additionally query Win32 ``GetFileAttributesW`` on Windows.
    """

    try:
        if path.is_symlink():
            return True
    except OSError:
        # Lstat failed — treat as unsafe rather than silently allowing.
        return True
    if os.name != "nt":
        return False
    try:
        import ctypes

        get_file_attributes = ctypes.windll.kernel32.GetFileAttributesW
        get_file_attributes.argtypes = [ctypes.c_wchar_p]
        get_file_attributes.restype = ctypes.c_uint32
        attrs = int(get_file_attributes(str(path)))
    except OSError:
        return False
    if attrs == _INVALID_FILE_ATTRIBUTES:
        return False
    return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)


def _path_chain(path: Path) -> list[Path]:
    """Return ``path`` and its parents from root to leaf for guard checks."""

    chain = [path]
    for parent in path.parents:
        chain.append(parent)
        if parent == parent.parent:
            break
    chain.reverse()
    return chain


def _has_reparse_component(path: Path) -> bool:
    """Return True when ``path`` or any existing ancestor is a reparse point."""

    for component in _path_chain(path):
        if not component.exists():
            continue
        if _has_reparse_point(component):
            return True
    return False


def _is_sensitive_appdata_path(path: Path) -> bool:
    """Return True for Windows AppData state except normal temp directories."""

    lowered = [part.lower() for part in path.parts if part]
    for index, part in enumerate(lowered):
        if part != "appdata":
            continue
        rest = lowered[index + 1 :]
        if len(rest) >= 2 and rest[0] == "local" and rest[1] in {"temp", "tmp"}:
            continue
        return True
    return False


def _is_sensitive_path(path: Path) -> bool:
    """Return True when any component of ``path`` names a sensitive location."""

    if _is_sensitive_appdata_path(path):
        return True
    for part in path.parts:
        if not part:
            continue
        if part.lower() in _SENSITIVE_BASENAMES or _SENSITIVE_PATTERN.match(part):
            return True
    return False


def assert_safe_source_folder(folder: Path) -> Path:
    """Resolve and validate a source folder before binding or scanning.

    Args:
        folder: Candidate directory path (may be relative or contain ``~``).

    Returns:
        The resolved real directory path.

    Raises:
        TypeError: ``folder`` is not a :class:`~pathlib.Path`.
        HTTPException 400: path is a reparse point, missing, not a directory,
            resolves onto a reparse point, or lands on a sensitive location.

    This is the shared safety core; it does NOT enforce project scoping. The
    caller binds the result (write mode) or compares it to an existing binding
    (check mode) via :func:`assert_within_binding`.
    """

    if not isinstance(folder, Path):
        raise TypeError("folder must be a pathlib.Path")
    candidate = folder.expanduser()
    # Reject reparse points on the *input* path before resolving, so a junction
    # named "AlSi10Mg实验" pointing at .codex cannot survive resolution.
    if _has_reparse_component(candidate.absolute()):
        raise HTTPException(
            status_code=400,
            detail="源目录是 symlink/junction/reparse point,拒绝以防跨界访问",
        )
    try:
        real = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"源目录不存在或无法访问: {candidate}",
        ) from exc
    if not real.is_dir():
        raise HTTPException(status_code=400, detail=f"路径不是目录: {real}")
    # Re-check after resolution: a component along the way may be a junction
    # whose target the caller did not name explicitly.
    if _has_reparse_component(real):
        raise HTTPException(
            status_code=400,
            detail="解析后的真实路径仍含 reparse point,拒绝",
        )
    if _is_sensitive_path(real):
        raise HTTPException(
            status_code=400,
            detail="源目录落在敏感区域(.env*/.git/.claude/.codex/credential 等),拒绝",
        )
    return real


def assert_within_binding(real_path: Path, binding_real: Path) -> None:
    """Check-mode guard: ``real_path`` must equal or sit under the bound root.

    Args:
        real_path: Resolved folder the caller wants to scan.
        binding_real: Resolved folder previously bound to the project.

    Raises:
        HTTPException 403: ``real_path`` escapes the project's bound root.
    """

    if not isinstance(real_path, Path):
        raise TypeError("real_path must be a pathlib.Path")
    if not isinstance(binding_real, Path):
        raise TypeError("binding_real must be a pathlib.Path")
    try:
        checked_path = real_path.expanduser().resolve(strict=True)
        checked_binding = binding_real.expanduser().resolve(strict=True)
        inside = checked_path == checked_binding or checked_path.is_relative_to(checked_binding)
    except (OSError, TypeError, ValueError):
        inside = False
    if not inside:
        raise HTTPException(
            status_code=403,
            detail="源目录与项目绑定的 source_folder_ref 不一致,拒绝扫描",
        )


def assert_bound_source_folder(real_path: Path, source_folder_ref: object) -> None:
    """Require a project-scoped ``source_folder_ref`` before ingesting files.

    Args:
        real_path: Resolved folder the caller wants to scan or ingest from.
        source_folder_ref: Project metadata payload persisted by the desktop
            picker. It must contain a non-empty backend-only ``path`` field.

    Raises:
        HTTPException 403: project metadata still uses a legacy unbound
            ``source_folder`` or the stored ref does not match ``real_path``.
    """

    if not isinstance(real_path, Path):
        raise TypeError("real_path must be a pathlib.Path")
    if not isinstance(source_folder_ref, dict):
        raise HTTPException(
            status_code=403,
            detail="项目 source_folder 缺少 source_folder_ref 绑定,请重新通过桌面端选择文件夹",
        )
    raw_binding_path = source_folder_ref.get("path")
    if not isinstance(raw_binding_path, str) or not raw_binding_path.strip():
        raise HTTPException(
            status_code=403,
            detail="项目 source_folder_ref 缺少绑定路径,请重新通过桌面端选择文件夹",
        )
    assert_within_binding(real_path, Path(raw_binding_path))


def build_binding(project_id: str, real_path: Path, bound_at: str) -> SourceFolderBinding:
    """Construct a :class:`SourceFolderBinding` with a privacy-safe display name.

    Args:
        project_id: Owning project identifier.
        real_path: Resolved source folder (already validated).
        bound_at: ISO-8601 UTC timestamp supplied by the caller.

    Returns:
        A frozen binding whose ``display_name`` is the directory basename only.
    """

    if not project_id or not isinstance(project_id, str):
        raise ValueError("project_id must be a non-empty string")
    if not isinstance(real_path, Path):
        raise TypeError("real_path must be a pathlib.Path")
    if not bound_at:
        raise ValueError("bound_at must be a non-empty ISO timestamp")
    return SourceFolderBinding(
        project_id=project_id,
        real_path=real_path,
        display_name=real_path.name or "source",
        bound_at=bound_at,
    )


def binding_ref_payload(binding: SourceFolderBinding, *, bound_by: str) -> dict[str, str]:
    """Serialize a binding into the project-metadata ``source_folder_ref`` slot.

    The stored payload keeps the absolute path for backend use (scan needs it)
    but MCP responses must project it away — only ``ref_id`` / ``display_name``
    leave the backend. See plan §7 path-privacy boundary.
    """

    if not bound_by:
        raise ValueError("bound_by must be a non-empty string")
    return {
        "path": str(binding.real_path),
        "display_name": binding.display_name,
        "bound_at": binding.bound_at,
        "bound_by": bound_by,
    }
