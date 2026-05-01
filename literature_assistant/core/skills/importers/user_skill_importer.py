# -*- coding: utf-8 -*-
"""User Skill import pipeline (TASK-185).

Imports user skill packages from local directories into a managed root,
validates manifests, records hash/origin/installed_at, and sets default
disabled state.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import logging
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from skills.user_manifest import (
    validate_manifest,
    parse_skill_md_frontmatter,
    ManifestValidationError,
    UserSkillManifest,
    MAX_PACKAGE_FILES,
    MAX_SINGLE_FILE_BYTES,
    MAX_PACKAGE_BYTES,
)
from skills.persistence import SkillInstallMetadata, write_install_metadata

logger = logging.getLogger("UserSkillImporter")


@dataclass
class ImportResult:
    """Result of a skill import operation."""
    success: bool
    error_code: str = ""
    skill_id: str = ""
    manifest: UserSkillManifest | None = None
    installed_path: str = ""
    content_hash: str = ""
    origin: str = ""
    installed_at: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "success": self.success,
            "error_code": self.error_code,
            "skill_id": self.skill_id,
            "installed_path": self.installed_path,
            "content_hash": self.content_hash,
            "origin": self.origin,
            "installed_at": self.installed_at,
            "errors": self.errors,
            "warnings": self.warnings,
        }
        if self.manifest:
            result["manifest"] = {
                "id": self.manifest.id,
                "name": self.manifest.name,
                "version": self.manifest.version,
                "kind": self.manifest.kind,
                "high_risk_flags": self.manifest.high_risk_flags,
            }
        return result


def _failure_result(
    *,
    error_code: str,
    origin: str,
    errors: list[str],
    skill_id: str = "",
    manifest: UserSkillManifest | None = None,
) -> ImportResult:
    """Build a standardized failed import result."""
    return ImportResult(
        success=False,
        error_code=error_code,
        skill_id=skill_id,
        manifest=manifest,
        origin=origin,
        errors=errors,
    )


def compute_directory_hash(dir_path: Path) -> str:
    """Compute a deterministic SHA-256 hash of all files in a directory."""
    hasher = hashlib.sha256()
    for file_path in sorted(dir_path.rglob("*")):
        if file_path.is_file():
            hasher.update(str(file_path.relative_to(dir_path)).encode())
            hasher.update(file_path.read_bytes())
    return hasher.hexdigest()


def validate_package_size(source_dir: Path) -> list[str]:
    """Check that the package respects size and file count limits."""
    errors: list[str] = []
    file_count = 0
    total_bytes = 0

    for file_path in source_dir.rglob("*"):
        if not file_path.is_file():
            continue
        file_count += 1
        size = file_path.stat().st_size
        total_bytes += size

        if size > MAX_SINGLE_FILE_BYTES:
            errors.append(
                f"File '{file_path.relative_to(source_dir)}' exceeds "
                f"{MAX_SINGLE_FILE_BYTES // 1024}KB limit ({size} bytes)"
            )

    if file_count > MAX_PACKAGE_FILES:
        errors.append(f"Package has {file_count} files, exceeds limit of {MAX_PACKAGE_FILES}")
    if total_bytes > MAX_PACKAGE_BYTES:
        errors.append(f"Package total size {total_bytes} bytes exceeds {MAX_PACKAGE_BYTES // (1024*1024)}MB limit")

    return errors


def _should_skip_archive_member(relative_path: PurePosixPath) -> bool:
    """Skip archive metadata that should not participate in user skill imports."""
    if not relative_path.parts:
        return True
    return relative_path.parts[0] == "__MACOSX" or relative_path.name == ".DS_Store"


def _normalize_archive_member_name(member_name: str) -> PurePosixPath | None:
    """Normalize one archive member path and reject traversal outside the package root."""
    if not member_name:
        return None
    normalized_name = member_name.replace("\\", "/")
    if normalized_name.endswith("/"):
        return None

    path = PurePosixPath(normalized_name)
    if path.is_absolute():
        raise ValueError(f"Archive contains absolute path entry: {member_name}")

    parts: list[str] = []
    for part in path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError(f"Archive path traversal detected: {member_name}")
        parts.append(part)
    if not parts:
        return None
    return PurePosixPath(*parts)


def _validate_archive_members(archive: zipfile.ZipFile) -> tuple[list[tuple[zipfile.ZipInfo, PurePosixPath]], list[str]]:
    """Validate archive members before extraction to limit traversal and resource abuse."""
    errors: list[str] = []
    members: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    seen_paths: set[str] = set()
    file_count = 0
    total_bytes = 0

    for info in archive.infolist():
        if info.is_dir():
            continue
        if info.flag_bits & 0x1:
            errors.append(f"Encrypted archive entry is not supported: {info.filename}")
            continue
        try:
            relative_path = _normalize_archive_member_name(info.filename)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if relative_path is None or _should_skip_archive_member(relative_path):
            continue

        path_key = relative_path.as_posix()
        if path_key in seen_paths:
            errors.append(f"Archive contains duplicate entry after normalization: {path_key}")
            continue
        seen_paths.add(path_key)

        file_count += 1
        total_bytes += info.file_size
        if info.file_size > MAX_SINGLE_FILE_BYTES:
            errors.append(
                f"Archive file '{path_key}' exceeds {MAX_SINGLE_FILE_BYTES // 1024}KB limit ({info.file_size} bytes)"
            )
        if file_count > MAX_PACKAGE_FILES:
            errors.append(f"Archive has {file_count} files, exceeds limit of {MAX_PACKAGE_FILES}")
        if total_bytes > MAX_PACKAGE_BYTES:
            errors.append(
                f"Archive total size {total_bytes} bytes exceeds {MAX_PACKAGE_BYTES // (1024 * 1024)}MB limit"
            )

        members.append((info, relative_path))

    if not members and not errors:
        errors.append("Archive does not contain any importable files")
    return members, errors


def _extract_archive_to_temp_dir(archive_path: Path, extract_root: Path) -> list[str]:
    """Safely materialize a validated skill archive into a temporary directory."""
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members, errors = _validate_archive_members(archive)
            if errors:
                return errors
            for info, relative_path in members:
                target_path = extract_root / Path(*relative_path.parts)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as src_handle, target_path.open("wb") as dest_handle:
                    shutil.copyfileobj(src_handle, dest_handle)
    except zipfile.BadZipFile:
        return [f"Source file is not a valid zip archive: {archive_path}"]
    except OSError as exc:
        return [f"Archive extraction failed: {exc}"]
    return []


def _resolve_package_root(source_root: Path) -> tuple[Path | None, list[str]]:
    """Resolve the effective package root from a directory or extracted archive tree."""
    if (source_root / "SKILL.md").exists():
        return source_root, []

    top_level_entries = [item for item in source_root.iterdir() if item.name != "__MACOSX"]
    top_level_dirs = [item for item in top_level_entries if item.is_dir()]
    top_level_files = [item for item in top_level_entries if item.is_file()]
    if len(top_level_dirs) == 1 and not top_level_files:
        candidate_root = top_level_dirs[0]
        if (candidate_root / "SKILL.md").exists():
            return candidate_root, []

    return None, ["SKILL.md not found in package root"]


@contextmanager
def prepared_import_source(source_path: Path) -> Iterator[Path]:
    """Yield a validated package root for a directory or zip-based import source."""
    if source_path.is_dir():
        package_root, errors = _resolve_package_root(source_path)
        if package_root is None:
            raise ValueError("; ".join(errors))
        yield package_root
        return

    if not source_path.is_file():
        raise ValueError(f"Source path is not a file or directory: {source_path}")

    if source_path.suffix.lower() != ".zip":
        raise ValueError(f"Source path must be a directory or a .zip archive: {source_path}")

    with tempfile.TemporaryDirectory(prefix="user-skill-import-") as temp_dir_str:
        extract_root = Path(temp_dir_str)
        extract_errors = _extract_archive_to_temp_dir(source_path, extract_root)
        if extract_errors:
            raise ValueError("; ".join(extract_errors))
        package_root, resolve_errors = _resolve_package_root(extract_root)
        if package_root is None:
            raise ValueError("; ".join(resolve_errors))
        yield package_root


def _import_prepared_user_skill(
    source_dir: Path,
    managed_root: Path,
    *,
    origin: str,
) -> ImportResult:
    """Import one validated directory tree into the managed skill root."""
    warnings: list[str] = []

    skill_md = source_dir / "SKILL.md"
    if not skill_md.exists():
        return _failure_result(
            error_code="MISSING_SKILL_MD",
            origin=origin,
            errors=["SKILL.md not found in package root"],
        )

    try:
        content = skill_md.read_text(encoding="utf-8")
        data = parse_skill_md_frontmatter(content)
        if not data:
            return _failure_result(
                error_code="INVALID_MANIFEST",
                origin=origin,
                errors=["SKILL.md has no valid frontmatter"],
            )
        manifest = validate_manifest(data)
    except ManifestValidationError as exc:
        return _failure_result(
            error_code="INVALID_MANIFEST",
            origin=origin,
            errors=exc.errors,
        )
    except Exception as exc:
        return _failure_result(
            error_code="INVALID_MANIFEST",
            origin=origin,
            errors=[f"Manifest parse error: {exc}"],
        )

    size_errors = validate_package_size(source_dir)
    if size_errors:
        return _failure_result(
            error_code="PACKAGE_LIMIT_EXCEEDED",
            skill_id=manifest.id,
            manifest=manifest,
            origin=origin,
            errors=size_errors,
        )

    if manifest.has_high_risk():
        warnings.append(
            f"Skill declares high-risk permissions: {', '.join(manifest.high_risk_flags)}"
        )

    content_hash = compute_directory_hash(source_dir)
    target_dir = managed_root / manifest.id
    if target_dir.exists():
        backup_dir = managed_root / ".rollback_snapshots" / f"{manifest.id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        backup_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(target_dir, backup_dir)
        shutil.rmtree(target_dir)
        warnings.append(f"Existing skill backed up to {backup_dir.name}")

    managed_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, target_dir)

    installed_at = datetime.now(timezone.utc).isoformat()
    meta = SkillInstallMetadata(
        skill_id=manifest.id,
        version=manifest.version,
        content_hash=content_hash,
        origin=origin,
        installed_at=installed_at,
        enabled=False,
        trust_level="untrusted",
        high_risk_flags=manifest.high_risk_flags,
        disabled_reason="Imported skill - not yet enabled",
        installed_path=str(target_dir),
    )
    write_install_metadata(target_dir, meta)

    logger.info(
        "Imported user skill %s v%s from %s (hash=%s)",
        manifest.id,
        manifest.version,
        origin,
        content_hash[:12],
    )

    return ImportResult(
        success=True,
        skill_id=manifest.id,
        manifest=manifest,
        installed_path=str(target_dir),
        content_hash=content_hash,
        origin=origin,
        installed_at=installed_at,
        errors=[],
        warnings=warnings,
    )


def import_user_skill(
    source_dir: Path,
    managed_root: Path,
    *,
    origin: str = "local",
) -> ImportResult:
    """Import a user skill package from a directory or zip archive into managed_root.

    Steps:
    1. Normalize a directory or zip source into a validated package root
    2. Parse and validate manifest
    3. Check package size limits
    4. Compute content hash
    5. Copy to managed root under {skill_id}/
    6. Write install metadata sidecar
    7. Return ImportResult

    The imported skill defaults to disabled state (not enabled).
    """
    source = Path(source_dir).expanduser().resolve()
    root = Path(managed_root).expanduser().resolve()
    if not source.exists():
        return _failure_result(
            error_code="SOURCE_PATH_NOT_FOUND",
            origin=origin,
            errors=[f"Source path does not exist: {source}"],
        )

    try:
        with prepared_import_source(source) as prepared_source:
            return _import_prepared_user_skill(prepared_source, root, origin=origin)
    except ValueError as exc:
        message = str(exc)
        error_code = "IMPORT_VALIDATION_FAILED"
        lowered = message.lower()
        if "valid zip archive" in lowered:
            error_code = "INVALID_ZIP_ARCHIVE"
        elif "path traversal" in lowered or "absolute path entry" in lowered or "duplicate entry" in lowered or "encrypted archive entry" in lowered:
            error_code = "UNSAFE_ARCHIVE_ENTRY"
        elif "skilL.md not found".lower() in lowered:
            error_code = "MISSING_SKILL_MD"
        elif "directory or a .zip archive" in lowered or "file or directory" in lowered:
            error_code = "UNSUPPORTED_SOURCE_PATH"
        return _failure_result(
            error_code=error_code,
            origin=origin,
            errors=[message],
        )
