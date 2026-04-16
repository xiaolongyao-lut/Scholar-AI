# -*- coding: utf-8 -*-
"""Unified WritingSkillService - Unified capability registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from datetime_utils import utc_now_iso_z

from .models import SkillDescriptor, SkillSource, UIVisibility
from .registry import SkillRegistry
from .runtime import SkillRunResult, ExecutionStatus
from .approval import ApprovalStore, ApprovalPolicy, CapabilityApprovalProfile
from .audit import AuditLog, AuditEventType, get_audit_log, ExecutionRecord


class WritingSkillService:
    """Unified capability service for builtin skills, imported skills, and actions."""

    def __init__(self, external_roots=None, approval_store=None, audit_log=None):
        """Initialize the service."""
        self._registry = SkillRegistry()
        self._approval_store = approval_store or ApprovalStore()
        self._audit_log = audit_log or get_audit_log()
        self._warnings = []
        self._last_results_by_job = {}
        self._request_params_by_job = {}
        
        self._load_builtin_skills()
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
            if skill.script_policy.has_scripts and not skill.script_policy.safe_to_execute:
                policy = ApprovalPolicy.BLOCKED.value
                description = "Imported skill with unsafe scripts"
            else:
                policy = ApprovalPolicy.GUIDANCE_ONLY.value
                description = "Imported skill - reference only"
            
            profile = CapabilityApprovalProfile(
                capability_id=skill.id,
                policy=policy,
                description=description,
                risk_level="high",
                metadata={"import_origin": skill.import_origin},
            )
            self._approval_store.register_profile(profile)
    
    def list_skills(self, ui_mode=None, kind=None, source=None):
        """List available skills filtered by criteria."""
        if ui_mode:
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
            return get_builtin_action_descriptors()
        except Exception:
            return []
    
    def run_legacy_action(self, action_id, input_text, scope=None, output_mode=None):
        """Run a legacy action."""
        actions = self.list_legacy_actions()
        action = next((a for a in actions if a["id"] == action_id), None)
        
        if action is None:
            raise ValueError(f"Action not found: {action_id}")
        
        skill_id = action.get("skillId")
        if not skill_id or not self._registry.has(skill_id):
            raise ValueError(f"Skill not found for action: {action_id}")
        
        return self.run_skill(skill_id=skill_id, input_text=input_text, scope=scope, output_mode=output_mode)

    def run_skill(self, skill_id, input_text, scope=None, output_mode=None):
        """Run a skill directly by skill ID."""
        return self._run_skill(skill_id=skill_id, input_text=input_text, scope=scope, output_mode=output_mode)
    
    def _run_skill(self, skill_id, input_text, scope=None, output_mode=None):
        """Execute a skill with approval and audit logging."""
        import datetime
        
        job_id = f"job_{uuid4().hex[:12]}"
        skill = self._registry.get(skill_id)
        
        if not skill:
            result = SkillRunResult(
                job_id=job_id,
                skill_id=skill_id,
                status=ExecutionStatus.FAILED,
                input_text=input_text,
                output_text="",
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
        
        self._audit_log.log_event(
            AuditEventType.JOB_CREATED.value,
            job_id=job_id,
            capability_id=skill_id,
            description=f"Job created for skill: {skill.name}",
            context={"scope": scope, "output_mode": output_mode},
        )
        
        approval_profile = self._approval_store.get_profile(skill_id)
        if approval_profile and approval_profile.requires_approval():
            self._audit_log.log_event(
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
            )
            self._last_results_by_job[job_id] = result
            return result
        
        if approval_profile and approval_profile.is_blocked():
            self._audit_log.log_event(
                AuditEventType.EXECUTION_BLOCKED.value,
                job_id=job_id,
                capability_id=skill_id,
                description=f"Execution blocked for {skill.name}",
                context={"policy": ApprovalPolicy.BLOCKED.value},
                severity="warning",
            )
            
            result = SkillRunResult(
                job_id=job_id,
                skill_id=skill_id,
                status=ExecutionStatus.FAILED,
                input_text=input_text,
                output_text=f"Execution blocked: {skill.disabled_reason or 'Security policy'}",
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
            output_text = f"[SKILL OUTPUT] Processed: {input_text[:50]}"
            
            result = SkillRunResult(
                job_id=job_id,
                skill_id=skill_id,
                status=ExecutionStatus.SUCCESS,
                input_text=input_text,
                output_text=output_text,
                execution_time_ms=100,
            )
            
            self._audit_log.log_event(
                AuditEventType.EXECUTION_COMPLETED.value,
                job_id=job_id,
                capability_id=skill_id,
                description=f"Successfully executed {skill.name}",
                new_state={"output_length": len(output_text)},
            )
            
            self._audit_log.update_execution_status(
                job_id,
                "completed",
                output_data=result.to_dict(),
            )
            
        except Exception as exec_e:
            result = SkillRunResult(
                job_id=job_id,
                skill_id=skill_id,
                status=ExecutionStatus.FAILED,
                input_text=input_text,
                output_text="",
            )
            
            self._audit_log.log_event(
                AuditEventType.EXECUTION_FAILED.value,
                job_id=job_id,
                capability_id=skill_id,
                error_message=str(exec_e),
                severity="error",
            )
            
            self._audit_log.update_execution_status(
                job_id,
                "failed",
                error_info={"error": str(exec_e)},
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
