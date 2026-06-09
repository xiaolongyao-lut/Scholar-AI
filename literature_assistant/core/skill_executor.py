# -*- coding: utf-8 -*-
"""Skill executor - routes skill types through audited guarded execution."""

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
from typing import Any, Final

from literature_assistant.core.skills.registry import SkillRegistry
from literature_assistant.core.skills.models import SkillDescriptor, SkillKind

logger = logging.getLogger(__name__)

_OUTPUT_CHAR_LIMIT: Final[int] = 10000
_SCRIPT_TIMEOUT_SECONDS: Final[int] = 30
_BLOCKED_ENV_NAME_PARTS: Final[tuple[str, ...]] = (
    "API_KEY",
    "AUTH",
    "BEARER",
    "CREDENTIAL",
    "KEY_POOL",
    "PASSWORD",
    "SECRET",
    "TOKEN",
)
_INHERITED_ENV_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "ALLUSERSPROFILE",
        "APPDATA",
        "COMSPEC",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "PYTHONPATH",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
)


@dataclass
class SkillExecutionResult:
    skill_id: str
    success: bool
    output: str
    error: str | None = None
    duration_ms: float = 0
    audit_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GuardedSubprocessPolicy:
    """Bounded subprocess policy for trusted scripted skills.

    The executor is not an OS sandbox. It supplies a minimal non-secret
    environment, a fixed working directory, wall-clock timeout, and output caps
    for scripts already marked safe by the Skill policy layer.
    """

    max_runtime_seconds: int = _SCRIPT_TIMEOUT_SECONDS
    max_output_chars: int = _OUTPUT_CHAR_LIMIT


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


def _is_blocked_env_name(name: str) -> bool:
    """Return whether an environment key is likely to contain secret material."""
    normalized = name.upper()
    return any(part in normalized for part in _BLOCKED_ENV_NAME_PARTS)


def _build_guarded_env(params_file: Path, audit_id: str, script_dir: Path) -> dict[str, str]:
    """Build the child-process environment without inheriting parent secrets.

    Args:
        params_file: Absolute JSON path supplied to the child script.
        audit_id: Stable audit id for the current execution.
        script_dir: Directory containing the script and its sibling helpers.

    Returns:
        Environment variables safe enough for a same-user guarded subprocess.
    """
    if not isinstance(params_file, Path):
        raise TypeError(f"params_file must be a pathlib.Path, got {type(params_file)!r}")
    if not audit_id:
        raise ValueError("audit_id must be non-empty")
    if not isinstance(script_dir, Path):
        raise TypeError(f"script_dir must be a pathlib.Path, got {type(script_dir)!r}")

    env: dict[str, str] = {}
    for name, value in os.environ.items():
        normalized = name.upper()
        if normalized not in _INHERITED_ENV_ALLOWLIST:
            continue
        if _is_blocked_env_name(normalized):
            continue
        env[name] = value

    repo_root = Path(__file__).resolve().parents[2]
    core_root = Path(__file__).resolve().parent
    existing_pythonpath = env.get("PYTHONPATH", "")
    pythonpath_parts = [str(script_dir.resolve()), str(repo_root), str(core_root)]
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONSAFEPATH": "1",
            "PYTHONUTF8": "1",
            "SKILL_GUARDED_SUBPROCESS": "1",
            "SKILL_PARAMS_FILE": str(params_file),
            "SKILL_AUDIT_ID": audit_id,
            "PYTHONPATH": os.pathsep.join(pythonpath_parts),
        }
    )
    return env


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


def _execute_scripted(skill: SkillDescriptor, params: dict[str, Any]) -> SkillExecutionResult:
    """Execute a scripted skill as a guarded subprocess."""
    audit_id = _generate_audit_id(skill.id)
    started = time.perf_counter()
    policy = GuardedSubprocessPolicy()

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

        params_file_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".json",
                prefix="litassist_skill_params_",
                delete=False,
            ) as params_file:
                json.dump(params, params_file, ensure_ascii=False)
                params_file_path = Path(params_file.name)

            env = _build_guarded_env(params_file_path, audit_id, script_path.parent)

            proc = subprocess.run(
                [sys.executable, str(script_path), "--params", str(params_file_path)],
                capture_output=True, text=True, timeout=policy.max_runtime_seconds,
                env=env, cwd=str(script_path.parent),
                check=False,
            )
        finally:
            if params_file_path is not None:
                params_file_path.unlink(missing_ok=True)

        if proc.returncode != 0:
            elapsed = (time.perf_counter() - started) * 1000
            err = SkillExecutionResult(
                skill_id=skill.id, success=False,
                output=proc.stdout[:policy.max_output_chars],
                error=proc.stderr[:500] or f"Exit code: {proc.returncode}",
                duration_ms=elapsed, audit_id=audit_id,
            )
            _audit_log(err, skill)
            return err

        output = proc.stdout[:policy.max_output_chars]
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
            error=f"Skill execution timed out after {policy.max_runtime_seconds}s",
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
