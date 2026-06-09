# -*- coding: utf-8 -*-
"""Persistence helpers for managed user skills.

The managed root is the trust boundary for imported user skills. Metadata is
stored beside each copied package so enabled state can survive process restarts.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from datetime_utils import utc_now_iso_z
from extension_secret_policy import require_no_plaintext_secret_config
from skills.user_manifest import UserSkillManifest, parse_skill_md_frontmatter, validate_manifest


INSTALL_METADATA_FILENAME = ".install_meta.json"
AUDIT_DIR_NAME = ".audit"
AUDIT_JSONL_FILENAME = "skill_audit.jsonl"
APPROVAL_DIR_NAME = ".approval"
APPROVAL_SQLITE_FILENAME = "skill_approvals.sqlite3"


@dataclass(frozen=True)
class SkillInstallMetadata:
    """Persistent install metadata for one managed user skill package."""

    skill_id: str
    version: str
    content_hash: str
    origin: str
    installed_at: str
    enabled: bool = False
    trust_level: str = "untrusted"
    high_risk_flags: list[str] = field(default_factory=list)
    disabled_reason: str | None = "Imported skill - not yet enabled"
    installed_path: str = ""
    updated_at: str | None = None
    last_run_at: str | None = None
    last_status: str | None = None
    last_warnings: list[str] = field(default_factory=list)
    config_values: dict[str, str] = field(default_factory=dict)
    credential_bindings: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary preserving stable metadata keys."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any], fallback_skill_id: str, fallback_path: Path) -> "SkillInstallMetadata":
        """Build metadata from a possibly older sidecar payload.

        Args:
            payload: Parsed `.install_meta.json` object.
            fallback_skill_id: Skill id inferred from the package directory.
            fallback_path: Package directory used when old metadata lacks path.
        """
        if not isinstance(payload, dict):
            raise TypeError("install metadata payload must be a JSON object")

        high_risk_flags = payload.get("high_risk_flags", [])
        if not isinstance(high_risk_flags, list):
            high_risk_flags = []
        last_warnings = payload.get("last_warnings", [])
        if not isinstance(last_warnings, list):
            last_warnings = []
        config_values = _string_dict(payload.get("config_values"))
        credential_bindings = _string_dict(payload.get("credential_bindings"))

        enabled = bool(payload.get("enabled", False))
        disabled_reason = payload.get("disabled_reason")
        if disabled_reason is not None and not isinstance(disabled_reason, str):
            disabled_reason = "Imported skill - not yet enabled"
        if not enabled and not disabled_reason:
            disabled_reason = "Imported skill - not yet enabled"

        installed_path = payload.get("installed_path")
        if not isinstance(installed_path, str) or not installed_path:
            installed_path = str(fallback_path)

        return cls(
            skill_id=str(payload.get("skill_id") or fallback_skill_id),
            version=str(payload.get("version") or "0.0.0"),
            content_hash=str(payload.get("content_hash") or ""),
            origin=str(payload.get("origin") or "managed_root"),
            installed_at=str(payload.get("installed_at") or ""),
            enabled=enabled,
            trust_level=str(payload.get("trust_level") or "untrusted"),
            high_risk_flags=[str(item) for item in high_risk_flags],
            disabled_reason=disabled_reason if not enabled else None,
            installed_path=installed_path,
            updated_at=str(payload["updated_at"]) if payload.get("updated_at") else None,
            last_run_at=str(payload["last_run_at"]) if payload.get("last_run_at") else None,
            last_status=str(payload["last_status"]) if payload.get("last_status") else None,
            last_warnings=[str(item) for item in last_warnings],
            config_values=config_values,
            credential_bindings=credential_bindings,
        )


def get_audit_jsonl_path(managed_root: Path) -> Path:
    """Return the managed-root audit JSONL path."""
    return managed_root / AUDIT_DIR_NAME / AUDIT_JSONL_FILENAME


def get_approval_sqlite_path(managed_root: Path) -> Path:
    """Return the managed-root SQLite path for approval requests and decisions."""
    return managed_root / APPROVAL_DIR_NAME / APPROVAL_SQLITE_FILENAME


def iter_managed_skill_dirs(managed_root: Path) -> Iterable[Path]:
    """Yield installed skill package directories under a managed root."""
    if not managed_root.exists():
        return []
    if not managed_root.is_dir():
        raise ValueError(f"Managed skill root is not a directory: {managed_root}")
    return (
        child
        for child in sorted(managed_root.iterdir(), key=lambda item: item.name)
        if child.is_dir() and not child.name.startswith(".") and (child / "SKILL.md").exists()
    )


def load_user_skill_manifest(skill_dir: Path) -> UserSkillManifest:
    """Load and validate a managed skill manifest from `SKILL.md`."""
    if not skill_dir.exists() or not skill_dir.is_dir():
        raise ValueError(f"Skill directory does not exist: {skill_dir}")

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise ValueError(f"SKILL.md not found: {skill_md}")

    frontmatter = parse_skill_md_frontmatter(skill_md.read_text(encoding="utf-8"))
    if not frontmatter:
        raise ValueError(f"SKILL.md has no valid frontmatter: {skill_md}")
    return validate_manifest(frontmatter)


def read_install_metadata(skill_dir: Path, fallback_manifest: UserSkillManifest | None = None) -> SkillInstallMetadata:
    """Read install metadata, returning safe defaults for older packages."""
    if not skill_dir.exists() or not skill_dir.is_dir():
        raise ValueError(f"Skill directory does not exist: {skill_dir}")

    fallback_skill_id = fallback_manifest.id if fallback_manifest is not None else skill_dir.name
    meta_path = skill_dir / INSTALL_METADATA_FILENAME
    if not meta_path.exists():
        return SkillInstallMetadata(
            skill_id=fallback_skill_id,
            version=fallback_manifest.version if fallback_manifest is not None else "0.0.0",
            content_hash="",
            origin="managed_root",
            installed_at="",
            enabled=False,
            high_risk_flags=fallback_manifest.high_risk_flags if fallback_manifest is not None else [],
            installed_path=str(skill_dir),
        )

    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    return SkillInstallMetadata.from_dict(payload, fallback_skill_id=fallback_skill_id, fallback_path=skill_dir)


def write_install_metadata(skill_dir: Path, metadata: SkillInstallMetadata) -> None:
    """Atomically write install metadata beside a managed skill package."""
    if not skill_dir.exists() or not skill_dir.is_dir():
        raise ValueError(f"Skill directory does not exist: {skill_dir}")

    payload = metadata.to_dict()
    meta_path = skill_dir / INSTALL_METADATA_FILENAME
    tmp_path = skill_dir / f"{INSTALL_METADATA_FILENAME}.tmp"
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(meta_path)


def _string_dict(value: Any) -> dict[str, str]:
    """Return a sanitized string dictionary for user-editable runtime settings."""
    if not isinstance(value, dict):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if isinstance(key, str) and key.strip() and item is not None
    }


def set_install_enabled(skill_dir: Path, enabled: bool, reason: str | None) -> SkillInstallMetadata:
    """Persist enabled state for an imported skill package."""
    manifest = load_user_skill_manifest(skill_dir)
    current = read_install_metadata(skill_dir, fallback_manifest=manifest)
    disabled_reason = None if enabled else (reason or "Disabled by user")
    updated = SkillInstallMetadata(
        skill_id=manifest.id,
        version=manifest.version,
        content_hash=current.content_hash,
        origin=current.origin,
        installed_at=current.installed_at,
        enabled=enabled,
        trust_level=current.trust_level,
        high_risk_flags=current.high_risk_flags or manifest.high_risk_flags,
        disabled_reason=disabled_reason,
        installed_path=str(skill_dir),
        updated_at=utc_now_iso_z(),
        last_run_at=current.last_run_at,
        last_status=current.last_status,
        last_warnings=current.last_warnings,
        config_values=current.config_values,
        credential_bindings=current.credential_bindings,
    )
    write_install_metadata(skill_dir, updated)
    return updated


def record_install_run_state(skill_dir: Path, status: str, warnings: list[str]) -> SkillInstallMetadata:
    """Persist the latest execution status for a managed user skill."""
    if not status:
        raise ValueError("status must not be empty")
    if not isinstance(warnings, list):
        raise TypeError("warnings must be a list of strings")

    manifest = load_user_skill_manifest(skill_dir)
    current = read_install_metadata(skill_dir, fallback_manifest=manifest)
    updated = SkillInstallMetadata(
        skill_id=current.skill_id,
        version=current.version,
        content_hash=current.content_hash,
        origin=current.origin,
        installed_at=current.installed_at,
        enabled=current.enabled,
        trust_level=current.trust_level,
        high_risk_flags=current.high_risk_flags,
        disabled_reason=current.disabled_reason,
        installed_path=str(skill_dir),
        updated_at=utc_now_iso_z(),
        last_run_at=utc_now_iso_z(),
        last_status=status,
        last_warnings=[str(item) for item in warnings],
        config_values=current.config_values,
        credential_bindings=current.credential_bindings,
    )
    write_install_metadata(skill_dir, updated)
    return updated


def set_install_runtime_settings(
    skill_dir: Path,
    config_values: dict[str, str],
    credential_bindings: dict[str, str],
) -> SkillInstallMetadata:
    """Persist non-sensitive Skill runtime settings beside a managed package."""
    if not isinstance(config_values, dict):
        raise TypeError("config_values must be a dictionary")
    if not isinstance(credential_bindings, dict):
        raise TypeError("credential_bindings must be a dictionary")
    require_no_plaintext_secret_config(config_values)

    manifest = load_user_skill_manifest(skill_dir)
    current = read_install_metadata(skill_dir, fallback_manifest=manifest)
    updated = SkillInstallMetadata(
        skill_id=current.skill_id,
        version=current.version,
        content_hash=current.content_hash,
        origin=current.origin,
        installed_at=current.installed_at,
        enabled=current.enabled,
        trust_level=current.trust_level,
        high_risk_flags=current.high_risk_flags,
        disabled_reason=current.disabled_reason,
        installed_path=str(skill_dir),
        updated_at=utc_now_iso_z(),
        last_run_at=current.last_run_at,
        last_status=current.last_status,
        last_warnings=current.last_warnings,
        config_values=_string_dict(config_values),
        credential_bindings=_string_dict(credential_bindings),
    )
    write_install_metadata(skill_dir, updated)
    return updated
