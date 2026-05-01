# -*- coding: utf-8 -*-
"""Runtime tests for user Skill execution policy."""

from __future__ import annotations

from pathlib import Path
import json

from skills.audit import AuditLog
from skills.approval import ApprovalDecision, ApprovalStore
from skills.runtime import ExecutionStatus, render_controlled_prompt_template
from skills.service import WritingSkillService


def _write_skill_package(
    root: Path,
    *,
    skill_id: str,
    kind: str = "transform",
    permissions: str = "  draft.read: true\n",
    script_policy: str = "  has_scripts: false\n  safe_to_execute: false\n",
    prompt: str = "Skill={{ skill_name }} Input={{ input_text }} Scope={{ scope }}",
) -> Path:
    """Write a minimal manifest-backed Skill package under a temp root."""
    package_dir = root / skill_id.replace(".", "-")
    package_dir.mkdir()
    (package_dir / "SKILL.md").write_text(
        (
            "---\n"
            f"id: {skill_id}\n"
            f"name: {skill_id}\n"
            "version: 1.0.0\n"
            f"kind: {kind}\n"
            "description: Runtime policy test skill.\n"
            "entry_mode: manual\n"
            "ui_visibility: skill_assisted\n"
            "supported_scopes: [selection]\n"
            "permissions:\n"
            f"{permissions}"
            "script_policy:\n"
            f"{script_policy}"
            "---\n"
            "\n"
            "# Runtime Skill\n"
        ),
        encoding="utf-8",
    )
    (package_dir / "prompts").mkdir()
    (package_dir / "prompts" / "main.txt").write_text(prompt, encoding="utf-8")
    return package_dir


def _build_service(tmp_path: Path) -> tuple[WritingSkillService, Path, Path]:
    """Return an isolated service, source root, and managed root."""
    source_root = tmp_path / "source"
    source_root.mkdir()
    managed_root = tmp_path / "managed"
    service = WritingSkillService(
        external_roots=None,
        approval_store=ApprovalStore(),
        audit_log=AuditLog(),
        managed_root=managed_root,
    )
    return service, source_root, managed_root


def _approve_latest_enable_request(service: WritingSkillService) -> None:
    """Approve the newest high-risk enable request in the isolated service."""
    pending = service.list_pending_approval_requests()
    assert len(pending) == 1
    service.decide_approval_request(
        request_id=pending[0]["request_id"],
        decision=ApprovalDecision.APPROVED.value,
        reason="pytest approval",
    )


def test_controlled_template_renderer_leaves_unknown_markers() -> None:
    """The renderer should substitute only allowlisted scalar variables."""
    rendered = render_controlled_prompt_template(
        "{{ input_text }} {{ unknown }}",
        {"input_text": "hello"},
    )

    assert rendered == "hello {{ unknown }}"


def test_enabled_prompt_only_skill_returns_structured_output(tmp_path: Path) -> None:
    """Enabled prompt-only Skills should run without model, network, or script access."""
    service, source_root, managed_root = _build_service(tmp_path)
    source_dir = _write_skill_package(source_root, skill_id="user.runtime.prompt")

    import_result = service.import_user_skill(source_dir, managed_root=managed_root, origin="pytest")
    assert import_result["success"] is True
    service.enable_skill("user.runtime.prompt")

    result = service.run_skill(
        skill_id="user.runtime.prompt",
        input_text="selected text",
        scope="selection",
        output_mode="plain",
    )

    assert result.status == ExecutionStatus.SUCCESS
    assert result.output_text == "Skill=user.runtime.prompt Input=selected text Scope=selection"
    assert result.structured_output["execution_mode"] == "prompt_only"
    assert result.structured_output["scope"] == "selection"
    assert result.audit_id is not None
    assert result.evidence_refs == []

    meta_path = managed_root / "user.runtime.prompt" / ".install_meta.json"
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    assert metadata["last_status"] == "success"
    assert isinstance(metadata["last_run_at"], str)


def test_disabled_imported_skill_is_blocked_before_runtime(tmp_path: Path) -> None:
    """Imported Skills remain non-executable until explicitly enabled."""
    service, source_root, managed_root = _build_service(tmp_path)
    source_dir = _write_skill_package(source_root, skill_id="user.runtime.disabled")
    service.import_user_skill(source_dir, managed_root=managed_root, origin="pytest")

    result = service.run_skill(skill_id="user.runtime.disabled", input_text="selected text")

    assert result.status == ExecutionStatus.FAILED
    assert result.structured_output["error_code"] == "skill_disabled"
    assert "not yet enabled" in result.output_text


def test_scripted_skill_remains_blocked_even_when_enabled(tmp_path: Path) -> None:
    """Scripted user Skills should not execute in the MVP runtime."""
    service, source_root, managed_root = _build_service(tmp_path)
    source_dir = _write_skill_package(
        source_root,
        skill_id="user.runtime.scripted",
        permissions="  draft.read: true\n  script.execute: true\n",
        script_policy="  has_scripts: true\n  safe_to_execute: false\n",
    )

    import_result = service.import_user_skill(source_dir, managed_root=managed_root, origin="pytest")
    assert import_result["success"] is True
    try:
        service.enable_skill("user.runtime.scripted")
    except PermissionError as exc:
        assert "Approval required" in str(exc)
    _approve_latest_enable_request(service)
    service.enable_skill("user.runtime.scripted")

    result = service.run_skill(skill_id="user.runtime.scripted", input_text="selected text")

    assert result.status == ExecutionStatus.FAILED
    assert result.structured_output["error_code"] in {"approval_blocked", "block_scripted_execution"}
    assert result.structured_output["security_assessment"]["runtime_executable"] is False
    assert result.structured_output["security_assessment"]["runtime_gate"] == "block_scripted_execution"
    assert result.audit_id is not None


def test_high_risk_network_permission_is_blocked_at_runtime(tmp_path: Path) -> None:
    """High-risk permissions are importable for visibility but not executable by default."""
    service, source_root, managed_root = _build_service(tmp_path)
    source_dir = _write_skill_package(
        source_root,
        skill_id="user.runtime.network",
        permissions="  draft.read: true\n  network: true\n",
    )

    import_result = service.import_user_skill(source_dir, managed_root=managed_root, origin="pytest")
    assert import_result["success"] is True
    try:
        service.enable_skill("user.runtime.network")
    except PermissionError as exc:
        assert "Approval required" in str(exc)
    _approve_latest_enable_request(service)
    service.enable_skill("user.runtime.network")

    result = service.run_skill(skill_id="user.runtime.network", input_text="selected text")

    assert result.status == ExecutionStatus.FAILED
    assert result.structured_output["error_code"] == "block_high_risk_permission"
    assert result.structured_output["security_assessment"]["runtime_executable"] is False
    assert result.structured_output["security_assessment"]["runtime_gate"] == "block_high_risk_permission"
    assert "High-risk Skill permissions" in result.structured_output["error"]

    metadata = json.loads((managed_root / "user.runtime.network" / ".install_meta.json").read_text(encoding="utf-8"))
    assert metadata["last_status"] == "failed"
    assert "High-risk Skill permissions" in metadata["last_warnings"][0]
