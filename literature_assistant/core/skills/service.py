# -*- coding: utf-8 -*-
"""Unified WritingSkillService - Unified capability registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4
import dataclasses
import re
import shutil

from datetime_utils import utc_now_iso_z
from project_paths import WORKSPACE_ARTIFACTS_ROOT

from .models import (
    SkillDescriptor,
    SkillKind,
    SkillSource,
    UIVisibility,
    SkillTrustLevel,
    ScriptPolicy,
)
from .registry import SkillRegistry
from .runtime import SkillRunResult, ExecutionStatus, render_controlled_prompt_template
from .approval import ApprovalDecision, ApprovalStore, ApprovalPolicy, CapabilityApprovalProfile
from .approval import ApprovalDecisionRecord, ApprovalRequest
from .audit import AuditLog, AuditEventType, ExecutionRecord
from .security_policy import (
    SkillSecurityPolicyError,
    assess_skill_security,
    is_skill_safe_for_legacy_action,
)
from .persistence import (
    get_approval_sqlite_path,
    get_audit_jsonl_path,
    iter_managed_skill_dirs,
    load_user_skill_manifest,
    record_install_run_state,
    read_install_metadata,
    set_install_runtime_settings,
    set_install_enabled,
)
from .user_manifest import UserSkillManifest


_SAFE_SKILL_EXPORT_ARCHIVE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.zip$")


def _safe_skill_export_stem(value: str, fallback: str = "skill") -> str:
    """Return a bounded ASCII-ish stem for Skill export archives.

    Args:
        value: Skill id or user-provided filename stem.
        fallback: Stem used when value has no safe characters.

    Returns:
        Filename stem safe to place under the Skill export directory.
    """
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._-")
    if not normalized:
        normalized = fallback
    return normalized[:96]


def _resolve_skill_export_path(skill_id: str, output_path: str | Path | None) -> Path:
    """Return a zip export path under the canonical Skill export root.

    Args:
        skill_id: Stable Skill id used for the default archive name.
        output_path: Optional filename only. Absolute paths and directory
            components are rejected to keep exports under workspace artifacts.

    Returns:
        Resolved path inside ``workspace_artifacts/skill_exports``.
    """
    safe_stem = _safe_skill_export_stem(skill_id)
    if output_path is None:
        filename = f"{safe_stem}.zip"
    else:
        filename = str(output_path or "").strip()
        if not filename:
            raise ValueError("output_path must be a non-empty zip filename")
        candidate = Path(filename)
        if candidate.is_absolute() or filename != candidate.name or "/" in filename or "\\" in filename:
            raise ValueError("output_path must be a filename under skill_exports")
        if not filename.lower().endswith(".zip"):
            filename = f"{filename}.zip"
        if not _SAFE_SKILL_EXPORT_ARCHIVE_RE.fullmatch(filename):
            raise ValueError("output_path must be a safe .zip filename")

    export_root = (WORKSPACE_ARTIFACTS_ROOT / "skill_exports").resolve()
    export_root.mkdir(parents=True, exist_ok=True)
    resolved = (export_root / filename).resolve()
    try:
        resolved.relative_to(export_root)
    except ValueError as exc:
        raise ValueError("output_path escapes skill export root") from exc
    return resolved


class WritingSkillService:
    """Unified capability service for builtin skills, imported skills, and actions."""

    def __init__(self, external_roots=None, approval_store=None, audit_log=None, managed_root=None):
        """Initialize the service."""
        self._registry = SkillRegistry()
        self._managed_root = Path(managed_root).expanduser().resolve() if managed_root else Path("skills/imported/user").resolve()
        self._approval_store = approval_store or ApprovalStore(get_approval_sqlite_path(self._managed_root))
        self._audit_log = audit_log or AuditLog(get_audit_jsonl_path(self._managed_root))
        self._warnings = []
        self._last_results_by_job = {}
        self._request_params_by_job = {}
        
        self._load_builtin_skills()
        self._load_managed_user_skills()
        roots = external_roots or []
        if roots:
            self._load_imported_skills(roots)
        
        self._setup_default_approval_policies()
    
    def _load_builtin_skills(self):
        """Load builtin prompt-backed skills."""
        try:
            from .loaders.prompt_builtin_loader import load_builtin_prompt_skills
            
            builtin_skills = load_builtin_prompt_skills(None)
            self._registry.register_many(builtin_skills)
            
            self._audit_log.log_event(
                AuditEventType.CAPABILITY_RESOLVED.value,
                description=f"Loaded {len(builtin_skills)} builtin skills",
                context={"skill_count": len(builtin_skills), "source": "builtin"},
            )
        except Exception as warn_e:
            warning = f"Could not load builtin skills: {warn_e}"
            self._warnings.append(warning)
            self._audit_log.log_event(
                AuditEventType.ERROR_OCCURRED.value,
                error_message=warning,
                severity="warning",
            )
    
    def _load_imported_skills(self, root_paths):
        """Load imported third-party skills."""
        try:
            from .importers import import_external_skill_dirs
            
            result = import_external_skill_dirs(root_paths, auto_disable=True)
            self._registry.register_many(result.descriptors)
            self._warnings.extend(result.warnings)
            
            self._audit_log.log_event(
                AuditEventType.CAPABILITY_RESOLVED.value,
                description=f"Loaded {len(result.descriptors)} imported skills",
                context={"skill_count": len(result.descriptors), "source": "imported"},
            )
        except Exception as warn_e:
            warning = f"Could not import external skills: {warn_e}"
            self._warnings.append(warning)
            self._audit_log.log_event(
                AuditEventType.ERROR_OCCURRED.value,
                error_message=warning,
                severity="warning",
            )

    def _load_managed_user_skills(self) -> None:
        """Load manifest-backed user skills from the managed install root."""
        try:
            skill_dirs = list(iter_managed_skill_dirs(self._managed_root))
        except ValueError as warn_e:
            warning = f"Could not load managed user skills: {warn_e}"
            self._warnings.append(warning)
            self._audit_log.log_event(
                AuditEventType.ERROR_OCCURRED.value,
                error_message=warning,
                severity="warning",
            )
            return

        loaded_count = 0
        for skill_dir in skill_dirs:
            try:
                manifest = load_user_skill_manifest(skill_dir)
                metadata = read_install_metadata(skill_dir, fallback_manifest=manifest)
                descriptor = self._descriptor_from_user_manifest(
                    manifest=manifest,
                    installed_path=skill_dir,
                    content_hash=metadata.content_hash,
                    origin=metadata.origin,
                    disabled_reason=None if metadata.enabled else metadata.disabled_reason,
                )
                descriptor = dataclasses.replace(
                    descriptor,
                    default_parameters={
                        **descriptor.default_parameters,
                        "last_run_at": metadata.last_run_at,
                        "last_status": metadata.last_status,
                        "last_warnings": metadata.last_warnings,
                        "config_values": dict(metadata.config_values),
                        "credential_bindings": dict(metadata.credential_bindings),
                    },
                )
                self._registry.register(descriptor)
                loaded_count += 1
            except Exception as warn_e:
                warning = f"Could not load managed user skill from {skill_dir}: {warn_e}"
                self._warnings.append(warning)
                self._audit_log.log_event(
                    AuditEventType.ERROR_OCCURRED.value,
                    error_message=warning,
                    severity="warning",
                    context={"skill_dir": str(skill_dir)},
                )

        if loaded_count:
            self._audit_log.log_event(
                AuditEventType.CAPABILITY_RESOLVED.value,
                description=f"Loaded {loaded_count} managed user skills",
                context={"skill_count": loaded_count, "source": "managed_user", "managed_root": str(self._managed_root)},
            )
    
    def _setup_default_approval_policies(self):
        """Set up default approval policies."""
        for skill in self._registry.list_by_source("builtin"):
            profile = CapabilityApprovalProfile(
                capability_id=skill.id,
                policy=ApprovalPolicy.AUTO_ALLOWED.value,
                description=f"Builtin skill: {skill.name}",
                risk_level="low",
                metadata={"skill_kind": skill.kind.value},
            )
            self._approval_store.register_profile(profile)
        
        for skill in self._registry.list_by_source("imported"):
            assessment = assess_skill_security(skill)
            if not assessment.runtime_executable and skill.script_policy.has_scripts:
                policy = ApprovalPolicy.BLOCKED.value
                description = assessment.block_reason or "Imported skill with unsafe scripts"
            else:
                policy = ApprovalPolicy.GUIDANCE_ONLY.value
                description = "Imported skill - reference only"
            
            profile = CapabilityApprovalProfile(
                capability_id=skill.id,
                policy=policy,
                description=description,
                risk_level=assessment.risk_level,
                metadata={
                    "import_origin": skill.import_origin,
                    "security_assessment": assessment.to_dict(),
                },
            )
            self._approval_store.register_profile(profile)
    
    def list_skills(self, ui_mode=None, kind=None, source=None):
        """List available skills filtered by criteria."""
        if source:
            skills = self._registry.list_all()
        elif ui_mode:
            skills = self._registry.list_by_ui_mode(ui_mode)
        else:
            skills = self._registry.list_all()
        
        if kind:
            skills = [s for s in skills if s.kind.value == kind]
        if source:
            skills = [s for s in skills if s.source.value == source]
        
        return [s.to_dict() for s in skills if not (s.disabled_reason and source != "imported")]
    
    def get_skill(self, skill_id):
        """Get a single skill descriptor by ID."""
        skill = self._registry.get(skill_id)
        return skill.to_dict() if skill else None

    def get_skill_security_assessment(self, skill_id: str) -> dict[str, Any] | None:
        """Return the machine-readable safety policy for one registered skill."""
        if not skill_id:
            raise ValueError("skill_id must not be empty")
        skill = self._registry.get(skill_id)
        if skill is None:
            return None
        return assess_skill_security(skill).to_dict()

    def has_skill(self, skill_id: str) -> bool:
        """Return whether a skill is registered in the current service."""
        if not skill_id:
            raise ValueError("skill_id must not be empty")
        return self._registry.has(skill_id)

    def get_transform_result(self, job_id: str) -> dict[str, Any] | None:
        """Return a legacy transform result payload for a completed skill job."""
        if not job_id:
            raise ValueError("job_id must not be empty")
        result = self._last_results_by_job.get(job_id)
        if result is None:
            return None
        request_params = self._request_params_by_job.get(job_id, {})
        return {
            "jobId": result.job_id,
            "actionId": request_params.get("action_id", ""),
            "skillId": result.skill_id,
            "inputText": result.input_text,
            "outputText": result.output_text,
            "scope": request_params.get("scope", "section"),
            "outputMode": request_params.get("output_mode", "word_safe"),
            "createdAt": result.timestamp,
            "applied": result.is_success(),
        }
    
    def list_skill_packs(self, ui_mode=None):
        """List skill packs for UI grouping."""
        packs = {}
        skills = self._registry.list_by_ui_mode(ui_mode) if ui_mode else self._registry.list_all()
        
        for skill in skills:
            group = skill.display_group or "general"
            if group not in packs:
                packs[group] = {
                    "id": group,
                    "name": group.replace("_", " ").title(),
                    "description": f"Skills in {group} group",
                    "skillIds": [],
                }
            packs[group]["skillIds"].append(skill.id)
        
        return list(packs.values())
    
    def list_capabilities(self):
        """List stable capabilities."""
        capabilities = []
        for skill in self._registry.list_all():
            if skill.disabled_reason and skill.source == SkillSource.IMPORTED:
                continue
            
            capability = {
                "id": skill.id,
                "name": skill.name,
                "description": skill.description,
                "kind": skill.kind.value,
            }
            capabilities.append(capability)
        
        return capabilities
    
    def list_legacy_actions(self):
        """List legacy-compatible actions."""
        try:
            from .loaders.prompt_builtin_loader import get_builtin_action_descriptors
            base_actions = get_builtin_action_descriptors()
        except Exception:
            base_actions = []

        # Append enabled safe user skills as custom actions.
        action_safe_kinds = {
            SkillKind.TRANSFORM,
            SkillKind.VALIDATOR,
            SkillKind.WORKFLOW,
            SkillKind.STYLE,
        }
        for skill in self._registry.list_by_source(SkillSource.IMPORTED.value):
            if skill.disabled_reason:
                continue
            if skill.kind not in action_safe_kinds:
                continue
            if not is_skill_safe_for_legacy_action(skill):
                continue
            
            base_actions.append({
                "id": f"skill:{skill.id}",
                "nameZh": skill.name,
                "nameEn": skill.name,
                "descriptionZh": skill.description,
                "descriptionEn": skill.description,
                "category": "other",
                "supportedScopes": skill.supported_scopes or ["selection", "section"],
                "icon": "Sparkles",
                "skillId": skill.id
            })

        return base_actions
    
    def run_legacy_action(self, action_id, input_text, scope=None, output_mode=None):
        """Run a legacy action."""
        actions = self.list_legacy_actions()
        action = next((a for a in actions if a["id"] == action_id), None)
        
        if action is None:
            raise ValueError(f"Action not found: {action_id}")
        
        skill_id = action.get("skillId")
        if not skill_id or not self._registry.has(skill_id):
            raise ValueError(f"Skill not found for action: {action_id}")

        result = self.run_skill(skill_id=skill_id, input_text=input_text, scope=scope, output_mode=output_mode)
        self._request_params_by_job[result.job_id] = {
            "action_id": action_id,
            "scope": scope or "section",
            "output_mode": output_mode or "word_safe",
        }
        return {
            "jobId": result.job_id,
            "status": result.status.value,
            "kind": "writing_transform",
            "message": "accepted" if result.is_success() else "failed",
        }

    def run_skill(self, skill_id, input_text, scope=None, output_mode=None):
        """Run a skill directly by skill ID."""
        return self._run_skill(skill_id=skill_id, input_text=input_text, scope=scope, output_mode=output_mode)

    def update_skill_runtime_settings(
        self,
        skill_id: str,
        *,
        config_values: dict[str, str],
        credential_bindings: dict[str, str],
    ) -> dict[str, Any]:
        """Persist user-editable config and credential references for a Skill."""
        if not isinstance(skill_id, str) or not skill_id.strip():
            raise ValueError("skill_id must be a non-empty string")
        if not isinstance(config_values, dict):
            raise TypeError("config_values must be a dictionary")
        if not isinstance(credential_bindings, dict):
            raise TypeError("credential_bindings must be a dictionary")

        skill = self._registry.get(skill_id)
        if skill is None:
            raise ValueError(f"Skill not found: {skill_id}")
        if skill.source != SkillSource.IMPORTED:
            raise ValueError("Builtin skills do not have user-editable runtime settings")

        skill_dir = self._resolve_managed_skill_root(skill)
        if skill_dir is None:
            raise ValueError(f"Skill {skill_id} is not installed under the managed root")

        metadata = set_install_runtime_settings(
            skill_dir,
            config_values=config_values,
            credential_bindings=credential_bindings,
        )

        updated = dataclasses.replace(
            skill,
            default_parameters={
                **skill.default_parameters,
                "config_values": dict(metadata.config_values),
                "credential_bindings": dict(metadata.credential_bindings),
            },
        )
        self._registry.register(updated)
        self._audit_log.log_event(
            AuditEventType.CAPABILITY_RESOLVED.value,
            capability_id=skill_id,
            description="Skill runtime settings updated",
            context={
                "config_field_count": len(metadata.config_values),
                "credential_binding_count": len(metadata.credential_bindings),
            },
        )
        return {
            "skill_id": skill_id,
            "config_values": dict(metadata.config_values),
            "credential_bindings": dict(metadata.credential_bindings),
        }

    def import_user_skill(self, source_path: str | Path, managed_root: str | Path | None = None, origin: str = "user_import") -> dict[str, Any]:
        """Import a manifest-backed user skill from a directory or zip archive.

        Args:
            source_path: Local directory or `.zip` archive that contains `SKILL.md`.
            managed_root: DEPRECATED. Install root is now fixed server-side. This parameter
                          is ignored for security (path traversal prevention).
            origin: Human-readable import origin stored in metadata.

        Returns:
            Machine-readable import result.

        Raises:
            ValueError: If paths are malformed or validation fails.

        Security:
            The install root is hardcoded to `skills/imported/user` to prevent
            clients from controlling the installation directory via API calls.
            Previous versions allowed `managed_root` in the request, which created
            a path traversal vulnerability.
        """
        source = Path(source_path).expanduser().resolve()
        if not source.exists():
            raise ValueError(f"Source path does not exist: {source}")
        if not source.is_dir() and not source.is_file():
            raise ValueError(f"Source path is not a file or directory: {source}")

        # Security: Fixed installation root, ignoring any client-provided value
        root = Path("skills/imported/user").resolve()
        from .importers.user_skill_importer import import_user_skill as import_user_skill_package

        result = import_user_skill_package(source, root, origin=origin)
        if not result.success:
            self._audit_log.log_event(
                AuditEventType.ERROR_OCCURRED.value,
                description="User skill import failed",
                context={"source_path": str(source), "errors": result.errors},
                severity="warning",
            )
            return result.to_dict()

        if result.manifest is None:
            self._audit_log.log_event(
                AuditEventType.ERROR_OCCURRED.value,
                description="User skill import succeeded without manifest",
                context={"source_path": str(source)},
                severity="warning",
            )
            return result.to_dict()

        descriptor = self._descriptor_from_user_manifest(
            manifest=result.manifest,
            installed_path=Path(result.installed_path),
            content_hash=result.content_hash,
            origin=result.origin,
            disabled_reason="Imported skill - not yet enabled",
        )
        self._registry.register(descriptor)
        self._register_imported_approval_profile(descriptor)
        self._audit_log.log_event(
            AuditEventType.CAPABILITY_RESOLVED.value,
            capability_id=descriptor.id,
            description=f"Imported user skill: {descriptor.name}",
            context={
                "origin": result.origin,
                "content_hash": result.content_hash,
                "installed_path": result.installed_path,
                "high_risk_flags": result.manifest.high_risk_flags,
            },
        )
        return result.to_dict()

    def enable_skill(self, skill_id: str) -> dict[str, Any]:
        """Enable an imported user skill in the live registry."""
        skill = self._registry.get(skill_id)
        if skill is None:
            raise ValueError(f"Skill not found: {skill_id}")
        if skill.source == SkillSource.BUILTIN:
            return {"skill_id": skill_id, "enabled": True, "reason": None}

        approval_request = self._ensure_high_risk_enable_approval(skill)
        if approval_request is not None:
            raise PermissionError(
                f"Approval required before enabling high-risk skill: {approval_request.request_id}"
            )

        self._persist_imported_skill_state(skill, enabled=True, reason=None)
        updated = dataclasses.replace(skill, disabled_reason=None)
        self._registry.register(updated)
        self._register_imported_approval_profile(updated)
        self._audit_log.log_event(
            AuditEventType.CAPABILITY_RESOLVED.value,
            capability_id=skill_id,
            description=f"Skill enabled: {skill.name}",
            new_state={"enabled": True},
        )
        return {"skill_id": skill_id, "enabled": True, "reason": None}

    def disable_skill(self, skill_id: str, reason: str = "Disabled by user") -> dict[str, Any]:
        """Disable an imported user skill in the live registry."""
        skill = self._registry.get(skill_id)
        if skill is None:
            raise ValueError(f"Skill not found: {skill_id}")
        if skill.source == SkillSource.BUILTIN:
            raise ValueError("Builtin skills cannot be disabled through user skill management")

        self._persist_imported_skill_state(skill, enabled=False, reason=reason)
        updated = dataclasses.replace(skill, disabled_reason=reason)
        self._registry.register(updated)
        self._register_imported_approval_profile(updated)
        self._audit_log.log_event(
            AuditEventType.CAPABILITY_RESOLVED.value,
            capability_id=skill_id,
            description=f"Skill disabled: {skill.name}",
            new_state={"enabled": False, "reason": reason},
        )
        return {"skill_id": skill_id, "enabled": False, "reason": reason}

    def uninstall_skill(self, skill_id: str, *, dry_run: bool = False) -> dict[str, Any]:
        """Uninstall a managed user skill after creating a rollback snapshot."""
        if not skill_id:
            raise ValueError("skill_id must not be empty")
        skill = self._registry.get(skill_id)
        if skill is None:
            raise ValueError(f"Skill not found: {skill_id}")
        if skill.source == SkillSource.BUILTIN:
            raise ValueError("Builtin skills cannot be uninstalled")
        skill_dir = self._resolve_managed_skill_root(skill)
        if skill_dir is None:
            raise ValueError(f"Managed skill directory not found for: {skill_id}")

        backup_dir = self._build_skill_backup_path(skill_id)
        warnings: list[str] = []
        if dry_run:
            return {
                "skill_id": skill_id,
                "uninstalled": False,
                "dry_run": True,
                "backup_path": str(backup_dir),
                "removed_path": str(skill_dir),
                "warnings": warnings,
            }

        backup_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_dir, backup_dir)
        shutil.rmtree(skill_dir)
        self._registry.unregister(skill_id)
        self._audit_log.log_event(
            AuditEventType.CAPABILITY_RESOLVED.value,
            capability_id=skill_id,
            description=f"Skill uninstalled: {skill.name}",
            previous_state={"installed_path": str(skill_dir)},
            new_state={"uninstalled": True, "backup_path": str(backup_dir)},
        )
        return {
            "skill_id": skill_id,
            "uninstalled": True,
            "dry_run": False,
            "backup_path": str(backup_dir),
            "removed_path": str(skill_dir),
            "warnings": warnings,
        }

    def rollback_skill(self, skill_id: str, *, backup_path: str | Path | None = None) -> dict[str, Any]:
        """Restore a managed user skill from a rollback snapshot."""
        if not skill_id:
            raise ValueError("skill_id must not be empty")
        backup_dir = self._resolve_skill_backup_path(skill_id, backup_path)
        if backup_dir is None:
            raise ValueError(f"Rollback snapshot not found for: {skill_id}")

        backup_manifest = load_user_skill_manifest(backup_dir)
        if backup_manifest.id != skill_id:
            raise ValueError(
                f"Rollback snapshot skill id mismatch: expected {skill_id}, got {backup_manifest.id}"
            )
        target_dir = (self._managed_root / skill_id).resolve()
        try:
            target_dir.relative_to(self._managed_root.resolve())
        except ValueError as exc:
            raise ValueError("Resolved rollback target escaped managed root") from exc

        if target_dir.exists():
            broken_dir = self._build_skill_backup_path(f"{skill_id}-broken")
            broken_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(target_dir, broken_dir)
            shutil.rmtree(target_dir)
        shutil.copytree(backup_dir, target_dir)

        metadata = read_install_metadata(target_dir, fallback_manifest=backup_manifest)
        descriptor = self._descriptor_from_user_manifest(
            manifest=backup_manifest,
            installed_path=target_dir,
            content_hash=metadata.content_hash,
            origin=metadata.origin,
            disabled_reason=None if metadata.enabled else metadata.disabled_reason,
        )
        self._registry.register(descriptor)
        self._register_imported_approval_profile(descriptor)
        self._audit_log.log_event(
            AuditEventType.CAPABILITY_RESOLVED.value,
            capability_id=skill_id,
            description=f"Skill rolled back: {descriptor.name}",
            new_state={"restored_path": str(target_dir), "backup_path": str(backup_dir)},
        )
        return {
            "skill_id": skill_id,
            "rolled_back": True,
            "restored_path": str(target_dir),
            "backup_path": str(backup_dir),
            "warnings": [],
        }

    def export_user_skill(self, skill_id: str, output_path: str | Path | None = None) -> dict[str, Any]:
        """Export a user skill to a zip archive.

        J11 (2026-05-26): Export user skill package for backup/sharing.

        Args:
            skill_id: Skill ID to export.
            output_path: Optional output zip filename under workspace_artifacts/skill_exports.

        Returns:
            Export result dict with success/export_path/errors.

        Raises:
            ValueError: If skill not found or is builtin.
        """
        import zipfile
        from datetime_utils import utc_now_iso_z

        skill = self._registry.get(skill_id)
        if skill is None:
            raise ValueError(f"Skill not found: {skill_id}")
        if skill.source == SkillSource.BUILTIN:
            raise ValueError(f"Cannot export builtin skill: {skill_id}")

        # Get installed_path from default_parameters
        installed_path = skill.default_parameters.get("installed_path")
        if not isinstance(installed_path, str) or not installed_path:
            raise ValueError(f"Skill {skill_id} has no installed_path in default_parameters")

        skill_dir = Path(installed_path).resolve()
        if not skill_dir.exists() or not skill_dir.is_dir():
            raise ValueError(f"Skill directory not found: {skill_dir}")

        output_path = _resolve_skill_export_path(skill_id, output_path)

        # Create zip archive
        try:
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for file_path in skill_dir.rglob("*"):
                    if file_path.is_file():
                        arcname = file_path.relative_to(skill_dir)
                        zf.write(file_path, arcname)
        except Exception as exc:
            return {
                "success": False,
                "skill_id": skill_id,
                "export_path": "",
                "errors": [f"Export failed: {exc}"],
            }

        self._audit_log.log_event(
            AuditEventType.CAPABILITY_RESOLVED.value,
            capability_id=skill_id,
            description=f"Skill exported: {skill.name}",
            context={"export_path": str(output_path), "exported_at": utc_now_iso_z()},
        )

        return {
            "success": True,
            "skill_id": skill_id,
            "export_path": str(output_path),
            "errors": [],
        }


    def list_audit_events(self, skill_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """List recent skill audit events as API-safe dictionaries."""
        if limit < 1:
            raise ValueError("limit must be >= 1")
        events = self._audit_log.list_events()
        if skill_id:
            events = [event for event in events if event.capability_id == skill_id]
        return [event.to_dict() for event in events[-limit:]]

    def submit_approval_request(
        self,
        *,
        capability_id: str,
        capability_name: str,
        reason: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create and persist an approval request for a skill capability."""
        if not capability_id:
            raise ValueError("capability_id must not be empty")
        if not capability_name:
            raise ValueError("capability_name must not be empty")
        if not reason:
            raise ValueError("reason must not be empty")
        safe_context = context if isinstance(context, dict) else {}
        request = ApprovalRequest(
            request_id=f"appr_{uuid4().hex[:12]}",
            capability_id=capability_id,
            capability_name=capability_name,
            reason=reason,
            context=safe_context,
        )
        self._approval_store.submit_approval_request(request)
        self._audit_log.log_event(
            AuditEventType.APPROVAL_REQUESTED.value,
            capability_id=capability_id,
            description=f"Approval requested for {capability_name}",
            context={"approval_request_id": request.request_id, "reason": reason},
        )
        return request.to_dict()

    def get_approval_detail(self, request_id: str) -> dict[str, Any] | None:
        """Return one approval request and its decision history."""
        if not request_id:
            raise ValueError("request_id must not be empty")
        request = self._approval_store.get_request(request_id)
        if request is None:
            return None
        decisions = self._approval_store.list_decisions(request_id)
        latest = decisions[-1] if decisions else None
        return {
            "request": request.to_dict(),
            "latest_decision": latest.to_dict() if latest is not None else None,
            "decisions": [decision.to_dict() for decision in decisions],
        }

    def list_pending_approval_requests(self) -> list[dict[str, Any]]:
        """List approval requests that have no final approve/deny decision."""
        return [request.to_dict() for request in self._approval_store.get_pending_requests()]

    def decide_approval_request(
        self,
        *,
        request_id: str,
        decision: str,
        user_id: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Persist one approval decision and emit an audit event."""
        if not request_id:
            raise ValueError("request_id must not be empty")
        request = self._approval_store.get_request(request_id)
        if request is None:
            raise ValueError(f"Approval request not found: {request_id}")
        record = ApprovalDecisionRecord(
            request_id=request_id,
            decision=decision,
            user_id=user_id,
            reason=reason,
        )
        self._approval_store.record_decision(record)
        self._audit_log.log_event(
            AuditEventType.APPROVAL_DECIDED.value,
            capability_id=request.capability_id,
            description=f"Approval decision recorded for {request.capability_name}",
            context={
                "approval_request_id": request_id,
                "decision": decision,
                "has_user_id": bool(user_id),
            },
        )
        return record.to_dict()

    def _ensure_high_risk_enable_approval(self, skill: SkillDescriptor) -> ApprovalRequest | None:
        """Return a pending approval request when high-risk enable lacks approval."""
        if not self._skill_requires_enable_approval(skill):
            return None

        existing = self._find_latest_enable_approval(skill.id)
        if existing is not None:
            latest = self._approval_store.get_latest_decision(existing.request_id)
            if latest is not None and latest.decision == ApprovalDecision.APPROVED.value:
                return None
            if latest is not None and latest.decision == ApprovalDecision.DENIED.value:
                return self._submit_high_risk_enable_approval(skill)
            return existing
        return self._submit_high_risk_enable_approval(skill)

    def _skill_requires_enable_approval(self, skill: SkillDescriptor) -> bool:
        """Return whether enabling a user skill must be explicitly approved."""
        return assess_skill_security(skill).enable_requires_approval

    def _find_latest_enable_approval(self, skill_id: str) -> ApprovalRequest | None:
        """Return the newest approval request generated for high-risk skill enable."""
        requests = [
            request
            for request in self._approval_store.list_requests()
            if request.capability_id == skill_id and request.context.get("operation") == "enable_skill"
        ]
        return requests[-1] if requests else None

    def _submit_high_risk_enable_approval(self, skill: SkillDescriptor) -> ApprovalRequest:
        """Persist a high-risk enable request and write an audit event."""
        assessment = assess_skill_security(skill)
        risky_permissions = list(assessment.denied_operations)

        request = ApprovalRequest(
            request_id=f"appr_{uuid4().hex[:12]}",
            capability_id=skill.id,
            capability_name=skill.name,
            reason=assessment.approval_reason or f"Enable high-risk user skill permissions: {', '.join(risky_permissions)}",
            context={
                "operation": "enable_skill",
                "skill_id": skill.id,
                "permissions": risky_permissions,
                "security_assessment": assessment.to_dict(),
            },
        )
        self._approval_store.submit_approval_request(request)
        self._audit_log.log_event(
            AuditEventType.APPROVAL_REQUESTED.value,
            capability_id=skill.id,
            description=f"Approval required before enabling high-risk skill: {skill.name}",
            context={
                "approval_request_id": request.request_id,
                "permissions": risky_permissions,
                "security_assessment": assessment.to_dict(),
            },
            severity="warning",
        )
        return request

    def _register_imported_approval_profile(self, skill: SkillDescriptor) -> None:
        """Register the conservative approval profile for an imported skill."""
        assessment = assess_skill_security(skill)
        if not assessment.runtime_executable and skill.script_policy.has_scripts:
            policy = ApprovalPolicy.BLOCKED.value
            description = assessment.block_reason or "Imported skill with unsafe scripts"
        elif skill.disabled_reason:
            policy = ApprovalPolicy.GUIDANCE_ONLY.value
            description = "Imported skill - disabled or reference only"
        else:
            policy = ApprovalPolicy.GUIDANCE_ONLY.value
            description = "Imported skill - reference only"

        profile = CapabilityApprovalProfile(
            capability_id=skill.id,
            policy=policy,
            description=description,
            risk_level=assessment.risk_level,
            metadata={
                "import_origin": skill.import_origin,
                "trust_level": skill.trust_level.value,
                "security_assessment": assessment.to_dict(),
            },
        )
        self._approval_store.register_profile(profile)

    def _descriptor_from_user_manifest(
        self,
        *,
        manifest: UserSkillManifest,
        installed_path: Path,
        content_hash: str,
        origin: str,
        disabled_reason: str | None,
    ) -> SkillDescriptor:
        """Build a registry descriptor from a validated user skill manifest."""
        return SkillDescriptor(
            id=manifest.id,
            name=manifest.name,
            description=manifest.description,
            kind=SkillKind(manifest.kind),
            source=SkillSource.IMPORTED,
            entry_mode=manifest.entry_mode,
            supported_scopes=list(manifest.supported_scopes),
            ui_visibility=UIVisibility(manifest.ui_visibility),
            requires_assets=False,
            version=manifest.version,
            display_group=manifest.display_group,
            experimental=manifest.experimental,
            safe_to_execute=False,
            capability_refs=[],
            default_parameters={
                "permissions": manifest.permissions,
                "model_policy": manifest.model_policy,
                "root_policy": manifest.root_policy,
                "content_hash": content_hash,
                "installed_path": str(installed_path),
                "config_values": {},
                "credential_bindings": {},
                # Surface manifest extension fields to the frontend through
                # the existing descriptor channel,
                # so the SkillManager can render the credential-binding
                # wizard without adding a separate endpoint or modifying
                # SkillDescriptor's frozen schema.
                "required_credentials": [
                    {
                        "id": rc.id,
                        "label": rc.label,
                        "env": rc.env,
                        "kind": rc.kind,
                        "provider_hints": list(rc.provider_hints),
                        "required": rc.required,
                        "description": rc.description,
                    }
                    for rc in manifest.required_credentials
                ],
                "config_fields": [
                    {
                        "id": cf.id,
                        "label": cf.label,
                        "env": cf.env,
                        "type": cf.type,
                        "default": cf.default,
                        "required": cf.required,
                        "description": cf.description,
                        "options": cf.options,
                        "min": cf.min,
                        "max": cf.max,
                        "step": cf.step,
                    }
                    for cf in manifest.config_fields
                ],
            },
            import_origin=origin,
            summary_hint=manifest.privacy_notes,
            disabled_reason=disabled_reason,
            script_policy=ScriptPolicy(
                has_scripts=bool(manifest.script_policy.get("has_scripts", False)),
                safe_to_execute=False,
                disabled_reason="Scripts blocked by default" if manifest.script_policy.get("has_scripts") else None,
            ),
            trust_level=SkillTrustLevel.UNTRUSTED,
            tags=list(manifest.tags),
        )

    def _persist_imported_skill_state(self, skill: SkillDescriptor, *, enabled: bool, reason: str | None) -> None:
        """Persist imported skill enabled state when it belongs to the managed root."""
        installed_path = skill.default_parameters.get("installed_path")
        if not isinstance(installed_path, str) or not installed_path:
            return

        skill_dir = Path(installed_path).expanduser().resolve()
        if not skill_dir.exists():
            self._audit_log.log_event(
                AuditEventType.ERROR_OCCURRED.value,
                capability_id=skill.id,
                description="Imported skill state was not persisted because installed path is missing",
                severity="warning",
                context={"installed_path": str(skill_dir)},
            )
            return
        set_install_enabled(skill_dir, enabled=enabled, reason=reason)

    def _persist_imported_run_state(self, skill: SkillDescriptor, result: SkillRunResult) -> None:
        """Persist latest run status for managed imported skills."""
        skill_dir = self._resolve_managed_skill_root(skill)
        if skill_dir is None:
            return
        try:
            record_install_run_state(skill_dir, status=result.status.value, warnings=result.warnings)
        except Exception as warn_e:
            self._audit_log.log_event(
                AuditEventType.ERROR_OCCURRED.value,
                capability_id=skill.id,
                description="Imported skill run state was not persisted",
                error_message=str(warn_e),
                severity="warning",
            )

    def _resolve_managed_skill_root(self, skill: SkillDescriptor) -> Path | None:
        """Return the managed skill root for imported skills with installed packages."""
        installed_path = skill.default_parameters.get("installed_path")
        if not isinstance(installed_path, str) or not installed_path:
            return None
        try:
            skill_dir = Path(installed_path).expanduser().resolve()
            managed_root = self._managed_root.resolve()
            skill_dir.relative_to(managed_root)
        except (OSError, ValueError):
            return None
        return skill_dir if skill_dir.exists() and skill_dir.is_dir() else None

    def _build_skill_backup_path(self, skill_id: str) -> Path:
        """Return a unique rollback path under the managed root."""
        safe_skill_id = self._safe_skill_id_for_snapshot(skill_id)
        return self._managed_root / ".rollback_snapshots" / f"{safe_skill_id}-{utc_now_iso_z().replace(':', '').replace('-', '').replace('.', '')}"

    def _resolve_skill_backup_path(self, skill_id: str, backup_path: str | Path | None) -> Path | None:
        """Resolve an explicit or latest rollback snapshot for one skill."""
        rollback_root = (self._managed_root / ".rollback_snapshots").resolve()
        if backup_path is not None:
            candidate = Path(backup_path).expanduser().resolve()
            try:
                candidate.relative_to(rollback_root)
            except ValueError as exc:
                raise ValueError("Rollback snapshot path must stay under managed rollback root") from exc
            return candidate if candidate.exists() and candidate.is_dir() else None

        if not rollback_root.exists() or not rollback_root.is_dir():
            return None
        safe_skill_id = self._safe_skill_id_for_snapshot(skill_id)
        prefix = f"{safe_skill_id}-"
        broken_prefix = f"{safe_skill_id}-broken-"
        candidates = [
            child
            for child in rollback_root.iterdir()
            if child.is_dir() and child.name.startswith(prefix) and not child.name.startswith(broken_prefix)
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: item.stat().st_mtime)[-1].resolve()

    @staticmethod
    def _safe_skill_id_for_snapshot(skill_id: str) -> str:
        """Return a filesystem-safe skill id segment for rollback snapshot names."""
        safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in skill_id)
        return safe or "skill"

    def _read_managed_prompt_template(self, skill: SkillDescriptor) -> tuple[str, list[str]]:
        """Read an imported skill prompt template without leaving the managed root."""
        skill_root = self._resolve_managed_skill_root(skill)
        if skill_root is None:
            return "", ["No managed prompt template root is available for this skill"]

        candidate_paths = [skill_root / "prompts" / "main.txt", skill_root / "prompt.txt", skill_root / "SKILL.md"]
        for candidate in candidate_paths:
            try:
                resolved_candidate = candidate.resolve()
                resolved_candidate.relative_to(skill_root)
            except (OSError, ValueError):
                continue
            if resolved_candidate.exists() and resolved_candidate.is_file():
                return resolved_candidate.read_text(encoding="utf-8"), []

        return "", ["No prompt template file found; using controlled input echo"]

    def _execute_skill_body(
        self,
        *,
        skill: SkillDescriptor,
        job_id: str,
        input_text: str,
        scope: str | None,
        output_mode: str | None,
    ) -> SkillRunResult:
        """Execute safe prompt/workflow skills without script, network, or file writes."""
        import time

        start_time = time.perf_counter()
        warnings: list[str] = []
        execution_mode = "builtin"
        evidence_refs: list[dict[str, Any]] = []
        structured_output: dict[str, Any] = {
            "skill_id": skill.id,
            "skill_kind": skill.kind.value,
            "execution_mode": execution_mode,
            "scope": scope or "section",
            "output_mode": output_mode or "word_safe",
        }

        assessment = assess_skill_security(skill)
        structured_output["security_assessment"] = assessment.to_dict()
        if not assessment.runtime_executable:
            raise SkillSecurityPolicyError(assessment)

        if skill.source == SkillSource.IMPORTED:
            permissions = skill.default_parameters.get("permissions", {})
            if not isinstance(permissions, dict):
                permissions = {}

            template_text, prompt_warnings = self._read_managed_prompt_template(skill)
            warnings.extend(prompt_warnings)
            rendered_prompt = render_controlled_prompt_template(
                template_text or "{{ input_text }}",
                {
                    "input_text": input_text,
                    "skill_name": skill.name,
                    "scope": scope or "section",
                    "output_mode": output_mode or "word_safe",
                },
            )
            execution_mode = "workflow" if skill.kind == SkillKind.WORKFLOW else "prompt_only"
            output_text = rendered_prompt
            structured_output.update(
                {
                    "execution_mode": execution_mode,
                    "prompt_preview": rendered_prompt[:2000],
                    "permissions": permissions,
                    "requires_model_call": bool(skill.default_parameters.get("model_policy", {}).get("allow_llm", False))
                    if isinstance(skill.default_parameters.get("model_policy"), dict)
                    else False,
                }
            )
        else:
            output_text = f"[SKILL OUTPUT] Processed: {input_text[:50]}"
            structured_output.update({"execution_mode": "builtin", "prompt_refs": skill.prompt_template_refs})

        execution_time_ms = int((time.perf_counter() - start_time) * 1000)
        return SkillRunResult(
            job_id=job_id,
            skill_id=skill.id,
            status=ExecutionStatus.SUCCESS,
            input_text=input_text,
            output_text=output_text,
            execution_time_ms=execution_time_ms,
            warnings=warnings,
            structured_output=structured_output,
            evidence_refs=evidence_refs,
        )
    
    def _run_skill(self, skill_id, input_text, scope=None, output_mode=None):
        """Execute a skill with approval and audit logging."""
        job_id = f"job_{uuid4().hex[:12]}"
        skill = self._registry.get(skill_id)
        
        if not skill:
            result = SkillRunResult(
                job_id=job_id,
                skill_id=skill_id,
                status=ExecutionStatus.FAILED,
                input_text=input_text,
                output_text="",
                structured_output={"error_code": "skill_not_found"},
            )
            self._audit_log.log_event(
                AuditEventType.EXECUTION_FAILED.value,
                job_id=job_id,
                capability_id=skill_id,
                error_message="Skill not found",
                severity="error",
            )
            self._last_results_by_job[job_id] = result
            return result

        if skill.disabled_reason:
            audit_event = self._audit_log.log_event(
                AuditEventType.EXECUTION_BLOCKED.value,
                job_id=job_id,
                capability_id=skill_id,
                description=f"Execution blocked for disabled skill: {skill.name}",
                context={"disabled_reason": skill.disabled_reason},
                severity="warning",
            )
            result = SkillRunResult(
                job_id=job_id,
                skill_id=skill_id,
                status=ExecutionStatus.FAILED,
                input_text=input_text,
                output_text=f"Execution blocked: {skill.disabled_reason}",
                warnings=[skill.disabled_reason],
                structured_output={"error_code": "skill_disabled", "disabled_reason": skill.disabled_reason},
                audit_id=audit_event.event_id,
            )
            self._last_results_by_job[job_id] = result
            return result
        
        self._audit_log.log_event(
            AuditEventType.JOB_CREATED.value,
            job_id=job_id,
            capability_id=skill_id,
            description=f"Job created for skill: {skill.name}",
            context={"scope": scope, "output_mode": output_mode},
        )
        
        approval_profile = self._approval_store.get_profile(skill_id)
        if approval_profile and approval_profile.requires_approval():
            audit_event = self._audit_log.log_event(
                AuditEventType.APPROVAL_REQUESTED.value,
                job_id=job_id,
                capability_id=skill_id,
                description=f"User approval required for {skill.name}",
                context={"policy": ApprovalPolicy.REQUIRES_USER_APPROVAL.value},
            )
            
            result = SkillRunResult(
                job_id=job_id,
                skill_id=skill_id,
                status=ExecutionStatus.FAILED,
                input_text=input_text,
                output_text="",
                structured_output={"error_code": "approval_required"},
                audit_id=audit_event.event_id,
            )
            self._last_results_by_job[job_id] = result
            return result
        
        if approval_profile and approval_profile.is_blocked():
            assessment = assess_skill_security(skill)
            audit_event = self._audit_log.log_event(
                AuditEventType.EXECUTION_BLOCKED.value,
                job_id=job_id,
                capability_id=skill_id,
                description=f"Execution blocked for {skill.name}",
                context={
                    "policy": ApprovalPolicy.BLOCKED.value,
                    "security_assessment": assessment.to_dict(),
                },
                severity="warning",
            )
            
            result = SkillRunResult(
                job_id=job_id,
                skill_id=skill_id,
                status=ExecutionStatus.FAILED,
                input_text=input_text,
                output_text=f"Execution blocked: {assessment.block_reason or skill.disabled_reason or 'Security policy'}",
                structured_output={
                    "error_code": "approval_blocked",
                    "security_assessment": assessment.to_dict(),
                },
                audit_id=audit_event.event_id,
            )
            self._last_results_by_job[job_id] = result
            return result
        
        self._audit_log.log_event(
            AuditEventType.EXECUTION_STARTED.value,
            job_id=job_id,
            capability_id=skill_id,
            description=f"Executing skill: {skill.name}",
        )
        
        record = ExecutionRecord(
            job_id=job_id,
            capability_id=skill_id,
            started_at=utc_now_iso_z(),
            input_data={"input_text": input_text, "scope": scope, "output_mode": output_mode},
        )
        self._audit_log.register_execution(record)
        
        try:
            result = self._execute_skill_body(
                skill=skill,
                job_id=job_id,
                input_text=input_text,
                scope=scope,
                output_mode=output_mode,
            )

            audit_event = self._audit_log.log_event(
                AuditEventType.EXECUTION_COMPLETED.value,
                job_id=job_id,
                capability_id=skill_id,
                description=f"Successfully executed {skill.name}",
                new_state={"output_length": len(result.output_text), "execution_mode": result.structured_output.get("execution_mode")},
            )
            result = dataclasses.replace(result, audit_id=audit_event.event_id)
            self._persist_imported_run_state(skill, result)
            
            self._audit_log.update_execution_status(
                job_id,
                "completed",
                output_data=result.to_dict(),
            )
            
        except SkillSecurityPolicyError as exec_e:
            assessment = exec_e.assessment
            failure_message = str(exec_e)
            result = SkillRunResult(
                job_id=job_id,
                skill_id=skill_id,
                status=ExecutionStatus.FAILED,
                input_text=input_text,
                output_text="",
                warnings=[failure_message],
                structured_output={
                    "error_code": assessment.runtime_gate,
                    "error": failure_message,
                    "security_assessment": assessment.to_dict(),
                },
            )

            audit_event = self._audit_log.log_event(
                AuditEventType.EXECUTION_BLOCKED.value,
                job_id=job_id,
                capability_id=skill_id,
                error_message=failure_message,
                severity="warning",
                context={"security_assessment": assessment.to_dict()},
            )
            result = dataclasses.replace(result, audit_id=audit_event.event_id)
            self._persist_imported_run_state(skill, result)

            self._audit_log.update_execution_status(
                job_id,
                "blocked",
                error_info={"error": failure_message, "security_assessment": assessment.to_dict()},
            )

        except Exception as exec_e:
            failure_message = str(exec_e)
            result = SkillRunResult(
                job_id=job_id,
                skill_id=skill_id,
                status=ExecutionStatus.FAILED,
                input_text=input_text,
                output_text="",
                warnings=[failure_message],
                structured_output={"error_code": "skill_execution_failed", "error": failure_message},
            )
            
            audit_event = self._audit_log.log_event(
                AuditEventType.EXECUTION_FAILED.value,
                job_id=job_id,
                capability_id=skill_id,
                error_message=failure_message,
                severity="error",
            )
            result = dataclasses.replace(result, audit_id=audit_event.event_id)
            self._persist_imported_run_state(skill, result)
            
            self._audit_log.update_execution_status(
                job_id,
                "failed",
                error_info={"error": failure_message},
            )
        
        self._last_results_by_job[job_id] = result
        return result
    
    def get_warnings(self):
        """Return warnings from initialization."""
        return self._warnings.copy()
    
    def get_audit_log(self):
        """Get the audit log."""
        return self._audit_log
    
    def get_approval_store(self):
        """Get the approval store."""
        return self._approval_store


_service_instance = None


def get_writing_skill_service(external_roots=None):
    """Get or create global WritingSkillService."""
    global _service_instance
    if _service_instance is None:
        _service_instance = WritingSkillService(external_roots=external_roots)
    return _service_instance


def reset_writing_skill_service():
    """Reset service (for testing)."""
    global _service_instance
    _service_instance = None
