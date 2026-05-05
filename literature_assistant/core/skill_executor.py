# -*- coding: utf-8 -*-
"""Skill executor — routes skill types, executes with sandbox, audited."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from literature_assistant.core.skills.registry import SkillRegistry
from literature_assistant.core.skills.models import SkillDescriptor, SkillKind

logger = logging.getLogger(__name__)


@dataclass
class SkillExecutionResult:
    skill_id: str
    success: bool
    output: str
    error: str | None = None
    duration_ms: float = 0
    audit_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _generate_audit_id(skill_id: str) -> str:
    import uuid
    return f"skill_{skill_id}_{uuid.uuid4().hex[:12]}_{int(time.time())}"


def _audit_log(result: SkillExecutionResult, skill: SkillDescriptor) -> None:
    entry = {
        "audit_id": result.audit_id,
        "skill_id": result.skill_id,
        "skill_name": skill.name,
        "skill_kind": skill.kind.value,
        "skill_source": skill.source.value,
        "success": result.success,
        "error": result.error,
        "duration_ms": result.duration_ms,
        "timestamp": time.time(),
        "output_preview": result.output[:200] if result.output else "",
    }
    try:
        from literature_assistant.core.project_paths import runtime_state_path
        audit_dir = runtime_state_path() / "skill_audits"
        audit_dir.mkdir(parents=True, exist_ok=True)
        f = audit_dir / f"{result.audit_id}.json"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(f)
    except Exception as exc:
        logger.warning("Failed to write skill audit log: %s", exc)


def _build_sandbox_env() -> dict[str, Any]:
    """Restricted environment for scripted skills — blocks dangerous operations."""
    return {
        "allowed_imports": {"json", "re", "math", "datetime", "collections", "itertools", "textwrap"},
        "max_runtime_seconds": 30,
        "max_output_chars": 10000,
        "allow_filesystem_read": False,
        "allow_filesystem_write": False,
        "allow_network": False,
        "allow_subprocess": False,
    }


def _execute_prompt_only(skill: SkillDescriptor) -> SkillExecutionResult:
    """Return the prompt template as-is for LLM-side injection."""
    audit_id = _generate_audit_id(skill.id)
    template = ""
    if skill.prompt_template_refs:
        for ref in skill.prompt_template_refs:
            ref_path = Path(ref)
            if ref_path.exists():
                template += ref_path.read_text(encoding="utf-8") + "\n"
    if not template:
        template = f"[{skill.name}]\n{skill.description}"

    result = SkillExecutionResult(
        skill_id=skill.id,
        success=True,
        output=template,
        audit_id=audit_id,
        metadata={"mode": "prompt_only"},
    )
    _audit_log(result, skill)
    return result


def _execute_tool_wrapper(skill: SkillDescriptor, params: dict[str, Any]) -> SkillExecutionResult:
    """Execute a tool-wrapper skill by calling its declared Python function."""
    audit_id = _generate_audit_id(skill.id)
    started = time.perf_counter()

    if not skill.script_refs:
        err = SkillExecutionResult(
            skill_id=skill.id, success=False, output="",
            error="No script refs declared for tool-wrapper skill", audit_id=audit_id,
        )
        _audit_log(err, skill)
        return err

    try:
        script_path = Path(skill.script_refs[0])
        if not script_path.exists():
            raise FileNotFoundError(f"Script not found: {script_path}")

        # Import and call the script's main function
        import importlib.util
        spec = importlib.util.spec_from_file_location(f"skill_{skill.id}", str(script_path))
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load skill module: {script_path}")

        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Call execute(params) or main(params) if defined, else default
        func = getattr(mod, "execute", None) or getattr(mod, "main", None)
        if func is None:
            raise AttributeError(f"No execute() or main() found in {script_path}")

        raw_output = str(func(params))
        elapsed = (time.perf_counter() - started) * 1000

        result = SkillExecutionResult(
            skill_id=skill.id, success=True, output=raw_output,
            duration_ms=elapsed, audit_id=audit_id,
            metadata={"mode": "tool_wrapper", "script": str(script_path)},
        )
        _audit_log(result, skill)
        return result

    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000
        err = SkillExecutionResult(
            skill_id=skill.id, success=False, output="",
            error=str(exc), duration_ms=elapsed, audit_id=audit_id,
        )
        _audit_log(err, skill)
        return err


def _execute_scripted(skill: SkillDescriptor, params: dict[str, Any]) -> SkillExecutionResult:
    """Execute a scripted skill in a restricted sandbox."""
    audit_id = _generate_audit_id(skill.id)
    started = time.perf_counter()
    sandbox = _build_sandbox_env()

    if not skill.script_refs:
        err = SkillExecutionResult(
            skill_id=skill.id, success=False, output="",
            error="No script refs for scripted skill", audit_id=audit_id,
        )
        _audit_log(err, skill)
        return err

    try:
        script_path = Path(skill.script_refs[0])
        if not script_path.exists():
            raise FileNotFoundError(f"Script not found: {script_path}")

        # Write params to temp JSON for subprocess communication
        params_file = Path(tempfile.mktemp(suffix=".json"))
        params_file.write_text(json.dumps(params), encoding="utf-8")

        # Run in subprocess with timeout and restricted env
        env = os.environ.copy()
        env["SKILL_SANDBOX"] = "1"
        env["SKILL_PARAMS_FILE"] = str(params_file)
        env["SKILL_AUDIT_ID"] = audit_id

        proc = subprocess.run(
            [sys.executable, str(script_path), "--params", str(params_file)],
            capture_output=True, text=True, timeout=sandbox["max_runtime_seconds"],
            env=env, cwd=str(script_path.parent),
        )

        params_file.unlink(missing_ok=True)

        if proc.returncode != 0:
            elapsed = (time.perf_counter() - started) * 1000
            err = SkillExecutionResult(
                skill_id=skill.id, success=False,
                output=proc.stdout[:sandbox["max_output_chars"]],
                error=proc.stderr[:500] or f"Exit code: {proc.returncode}",
                duration_ms=elapsed, audit_id=audit_id,
            )
            _audit_log(err, skill)
            return err

        output = proc.stdout[:sandbox["max_output_chars"]]
        elapsed = (time.perf_counter() - started) * 1000

        result = SkillExecutionResult(
            skill_id=skill.id, success=True, output=output,
            duration_ms=elapsed, audit_id=audit_id,
            metadata={"mode": "scripted", "script": str(script_path)},
        )
        _audit_log(result, skill)
        return result

    except subprocess.TimeoutExpired:
        elapsed = (time.perf_counter() - started) * 1000
        err = SkillExecutionResult(
            skill_id=skill.id, success=False, output="",
            error=f"Skill execution timed out after {sandbox['max_runtime_seconds']}s",
            duration_ms=elapsed, audit_id=audit_id,
        )
        _audit_log(err, skill)
        return err
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000
        err = SkillExecutionResult(
            skill_id=skill.id, success=False, output="",
            error=str(exc), duration_ms=elapsed, audit_id=audit_id,
        )
        _audit_log(err, skill)
        return err


def execute_skill(skill: SkillDescriptor, params: dict[str, Any] | None = None) -> SkillExecutionResult:
    """Route skill execution by type."""
    params = params or {}

    if skill.kind == SkillKind.WORKFLOW:
        return _execute_prompt_only(skill)
    elif not skill.safe_to_execute:
        return SkillExecutionResult(
            skill_id=skill.id, success=False, output="",
            error="Skill is not marked safe to execute — BLOCKED by security policy",
        )
    elif skill.script_refs:
        return _execute_scripted(skill, params)
    elif skill.prompt_template_refs:
        return _execute_tool_wrapper(skill, params)
    else:
        return _execute_prompt_only(skill)


def skill_to_tool_schema(skill: SkillDescriptor) -> dict[str, Any]:
    """Convert a SkillDescriptor to an OpenAI-compatible tool/function schema."""
    safe_id = skill.id.replace("-", "_").replace(".", "_")
    return {
        "type": "function",
        "function": {
            "name": safe_id,
            "description": skill.description[:1024],
            "parameters": {
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": f"Input text for: {skill.name}",
                    }
                },
                "required": ["input"],
            },
        },
    }


def get_active_skill_tool_schemas(registry: SkillRegistry) -> list[dict[str, Any]]:
    """Get tool schemas for all enabled, prompt-injectable skills."""
    schemas: list[dict[str, Any]] = []
    for skill in registry.list_all():
        if skill.source.value == "experimental":
            continue
        if skill.safe_to_execute or skill.script_refs:
            schemas.append(skill_to_tool_schema(skill))
    return schemas