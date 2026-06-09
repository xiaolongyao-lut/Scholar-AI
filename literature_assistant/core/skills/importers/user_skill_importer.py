# -*- coding: utf-8 -*-
"""User Skill import pipeline.

Imports user skill packages from local directories into a managed root,
validates manifests, records hash/origin/installed_at, and sets default
disabled state.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import logging
import re
import shutil
import stat
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

_CODEX_COMPAT_VERSION = "0.1.0"
_SCRIPT_SUFFIXES = {".py", ".ps1", ".sh", ".js", ".mjs", ".ts", ".tsx", ".bat", ".cmd"}


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


def _slugify_skill_id(value: str) -> str:
    """Normalize a human/Codex skill name into the LA manifest id shape."""
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9._-]+", "-", lowered)
    slug = re.sub(r"[-_.]{2,}", "-", slug).strip("-_.")
    if len(slug) < 2:
        slug = f"{slug or 'skill'}-skill"
    return slug[:128]


def _has_script_files(source_dir: Path) -> bool:
    """Return true when a package carries executable script-like assets."""
    scripts_dir = source_dir / "scripts"
    if not scripts_dir.exists() or not scripts_dir.is_dir():
        return False
    return any(
        path.is_file() and path.suffix.lower() in _SCRIPT_SUFFIXES
        for path in scripts_dir.rglob("*")
    )


def _yaml_scalar(value: str) -> str:
    """Render a scalar conservatively for generated frontmatter."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _yaml_bool(value: bool) -> str:
    """Render a Python bool as lowercase YAML."""
    return "true" if value else "false"


def _strip_frontmatter(content: str) -> str:
    """Return markdown body after the first YAML frontmatter block."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return content
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1 :]).lstrip("\n")
    return content


def _render_skill_md_with_manifest(content: str, data: dict[str, Any]) -> str:
    """Preserve the markdown body while replacing frontmatter with LA fields."""
    permissions = data.get("permissions", {})
    script_policy = data.get("script_policy", {})
    model_policy = data.get("model_policy", {})
    root_policy = data.get("root_policy", {})
    tags = data.get("tags", [])
    scopes = data.get("supported_scopes", [])
    body = _strip_frontmatter(content)

    lines = [
        "---",
        f"id: {_yaml_scalar(str(data['id']))}",
        f"name: {_yaml_scalar(str(data['name']))}",
        f"version: {_yaml_scalar(str(data['version']))}",
        f"kind: {_yaml_scalar(str(data['kind']))}",
        f"description: {_yaml_scalar(str(data['description']))}",
        f"entry_mode: {_yaml_scalar(str(data['entry_mode']))}",
        f"ui_visibility: {_yaml_scalar(str(data['ui_visibility']))}",
        f"display_group: {_yaml_scalar(str(data['display_group']))}",
        f"experimental: {_yaml_bool(bool(data['experimental']))}",
        "supported_scopes:",
    ]
    for scope in scopes if isinstance(scopes, list) else ["full_draft"]:
        lines.append(f"  - {_yaml_scalar(str(scope))}")
    lines.append("tags:")
    for tag in tags if isinstance(tags, list) else ["codex-compatible"]:
        lines.append(f"  - {_yaml_scalar(str(tag))}")
    lines.append("permissions:")
    if isinstance(permissions, dict):
        for key in sorted(permissions):
            lines.append(f"  {key}: {_yaml_bool(bool(permissions[key]))}")
    lines.append("script_policy:")
    if isinstance(script_policy, dict):
        lines.append(f"  has_scripts: {_yaml_bool(bool(script_policy.get('has_scripts', False)))}")
        lines.append(f"  safe_to_execute: {_yaml_bool(bool(script_policy.get('safe_to_execute', False)))}")
    lines.append("model_policy:")
    if isinstance(model_policy, dict):
        lines.append(f"  allow_llm: {_yaml_bool(bool(model_policy.get('allow_llm', False)))}")
        lines.append(f"  allow_embedding: {_yaml_bool(bool(model_policy.get('allow_embedding', False)))}")
    lines.append("root_policy:")
    allowed_roots: list[str] = []
    if isinstance(root_policy, dict) and isinstance(root_policy.get("allowed_roots"), list):
        allowed_roots = [str(item) for item in root_policy["allowed_roots"]]
    lines.append("  allowed_roots:")
    for root in allowed_roots:
        lines.append(f"    - {_yaml_scalar(root)}")
    lines.extend(["---", "", body])
    return "\n".join(lines).rstrip() + "\n"


def _normalize_lite_skill_manifest(
    data: dict[str, Any],
    source_dir: Path,
) -> dict[str, Any]:
    """Fill LA manifest defaults for Codex-style name/description skills."""
    name = str(data.get("name") or source_dir.name).strip()
    description = str(data.get("description") or "").strip()
    has_scripts = _has_script_files(source_dir)
    permissions: dict[str, bool] = {"model.llm": True}
    if has_scripts:
        permissions.update({
            "files.read": True,
            "files.write": True,
            "script.execute": True,
        })
    return {
        **data,
        "id": str(data.get("id") or _slugify_skill_id(name or source_dir.name)),
        "name": name or source_dir.name,
        "version": str(data.get("version") or _CODEX_COMPAT_VERSION),
        "kind": str(data.get("kind") or "workflow"),
        "description": description or f"Imported Codex-compatible skill: {name or source_dir.name}",
        "entry_mode": str(data.get("entry_mode") or "assistant"),
        "ui_visibility": str(data.get("ui_visibility") or "skill_assisted"),
        "supported_scopes": data.get("supported_scopes") or ["full_draft"],
        "tags": data.get("tags") if isinstance(data.get("tags"), list) else ["codex-compatible"],
        "display_group": str(data.get("display_group") or "imported"),
        "experimental": bool(data.get("experimental", False)),
        "permissions": data.get("permissions") if isinstance(data.get("permissions"), dict) else permissions,
        "script_policy": data.get("script_policy") if isinstance(data.get("script_policy"), dict) else {
            "has_scripts": has_scripts,
            "safe_to_execute": False,
        },
        "model_policy": data.get("model_policy") if isinstance(data.get("model_policy"), dict) else {
            "allow_llm": True,
            "allow_embedding": False,
        },
        "root_policy": data.get("root_policy") if isinstance(data.get("root_policy"), dict) else {
            "allowed_roots": ["skill_root", "project_root"] if has_scripts else ["skill_root"],
        },
    }


def _should_try_lite_skill_compat(errors: list[str], data: dict[str, Any]) -> bool:
    """Allow Codex-style SKILL.md imports without weakening invalid LA manifests."""
    if not str(data.get("description") or "").strip():
        return False
    allowed_missing = {
        "Missing required field: id",
        "Missing required field: name",
        "Missing required field: version",
        "Missing required field: kind",
    }
    return bool(errors) and all(error in allowed_missing for error in errors)


def _parse_manifest_for_import(
    content: str,
    source_dir: Path,
) -> tuple[UserSkillManifest | None, str | None, list[str], str | None]:
    """Parse an LA manifest, with a guarded Codex-style compatibility path."""
    data = parse_skill_md_frontmatter(content)
    if not data:
        return None, None, ["SKILL.md has no valid frontmatter"], "INVALID_MANIFEST"
    try:
        return validate_manifest(data), None, [], None
    except ManifestValidationError as exc:
        if not _should_try_lite_skill_compat(exc.errors, data):
            return None, None, exc.errors, "INVALID_MANIFEST"
        normalized = _normalize_lite_skill_manifest(data, source_dir)
        try:
            manifest = validate_manifest(normalized)
        except ManifestValidationError as normalized_exc:
            return None, None, normalized_exc.errors, "INVALID_MANIFEST"
        normalized_content = _render_skill_md_with_manifest(content, normalized)
        warning = (
            "Imported Codex-style SKILL.md with synthesized LA manifest "
            f"fields (id={manifest.id}, version={manifest.version}, kind={manifest.kind})"
        )
        return manifest, normalized_content, [warning], None


def compute_directory_hash(dir_path: Path) -> str:
    """Compute a deterministic SHA-256 hash of all files in a directory."""
    hasher = hashlib.sha256()
    for file_path in sorted(dir_path.rglob("*")):
        if file_path.is_file():
            if file_path.is_symlink():
                raise ValueError(f"Package contains symbolic link: {file_path}")
            hasher.update(str(file_path.relative_to(dir_path)).encode())
            hasher.update(file_path.read_bytes())
    return hasher.hexdigest()


def validate_package_paths(source_dir: Path) -> list[str]:
    """Check that all package entries are regular paths inside the package root."""
    errors: list[str] = []
    try:
        source_root = source_dir.resolve(strict=True)
    except OSError as exc:
        return [f"Package root could not be resolved: {exc}"]

    for file_path in source_dir.rglob("*"):
        try:
            is_junction = bool(getattr(file_path, "is_junction", lambda: False)())
        except OSError:
            is_junction = False
        if file_path.is_symlink() or is_junction:
            errors.append(f"Package contains symbolic link: {file_path.relative_to(source_dir)}")
            continue
        try:
            file_path.resolve(strict=False).relative_to(source_root)
        except (OSError, ValueError):
            errors.append(f"Package path escapes root: {file_path.relative_to(source_dir)}")
    return errors


def validate_package_size(source_dir: Path) -> list[str]:
    """Check that the package respects size and file count limits."""
    errors: list[str] = []
    file_count = 0
    total_bytes = 0

    for file_path in source_dir.rglob("*"):
        if file_path.is_symlink():
            errors.append(f"Package contains symbolic link: {file_path.relative_to(source_dir)}")
            continue
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
        mode = info.external_attr >> 16
        if stat.S_IFMT(mode) == stat.S_IFLNK:
            errors.append(f"Archive symbolic link entry is not supported: {info.filename}")
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
        manifest, normalized_content, parse_messages, error_code = _parse_manifest_for_import(
            content,
            source_dir,
        )
        if manifest is None:
            return _failure_result(
                error_code=error_code or "INVALID_MANIFEST",
                origin=origin,
                errors=parse_messages,
            )
        warnings.extend(parse_messages)
    except Exception as exc:
        return _failure_result(
            error_code="INVALID_MANIFEST",
            origin=origin,
            errors=[f"Manifest parse error: {exc}"],
        )

    package_errors = validate_package_paths(source_dir) + validate_package_size(source_dir)
    if package_errors:
        error_code = (
            "UNSAFE_PACKAGE_PATH"
            if any("symbolic link" in error or "escapes root" in error for error in package_errors)
            else "PACKAGE_LIMIT_EXCEEDED"
        )
        return _failure_result(
            error_code=error_code,
            skill_id=manifest.id,
            manifest=manifest,
            origin=origin,
            errors=package_errors,
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
    if normalized_content is not None:
        (target_dir / "SKILL.md").write_text(normalized_content, encoding="utf-8")

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
        elif (
            "path traversal" in lowered
            or "absolute path entry" in lowered
            or "duplicate entry" in lowered
            or "encrypted archive entry" in lowered
            or "symbolic link entry" in lowered
        ):
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
