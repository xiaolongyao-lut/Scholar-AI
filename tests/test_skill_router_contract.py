# -*- coding: utf-8 -*-
"""Contract tests for user skill management routes."""

from __future__ import annotations

from pathlib import Path
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.skills_router as skills_router_module
from skills.audit import AuditLog
from skills.approval import ApprovalDecision, ApprovalStore
from skills.service import WritingSkillService


MINIMAL_SKILL_MD = """---
id: user.router.skill
name: Router Skill
version: 1.0.0
kind: transform
description: Router contract test skill.
entry_mode: manual
ui_visibility: skill_assisted
supported_scopes: [selection]
permissions:
  draft.read: true
script_policy:
  has_scripts: false
  safe_to_execute: false
---

# Router Skill
"""


def _build_client(monkeypatch, tmp_path: Path) -> tuple[TestClient, WritingSkillService, Path, Path]:
    """Create an isolated skill router client with a temporary service."""

    managed_root = tmp_path / "managed-skills"
    service = WritingSkillService(
        external_roots=None,
        approval_store=ApprovalStore(),
        audit_log=AuditLog(),
        managed_root=managed_root,
    )
    monkeypatch.setattr(skills_router_module, "get_skill_service", lambda: service)

    app = FastAPI()
    app.include_router(skills_router_module.router)
    client = TestClient(app)

    source_dir = tmp_path / "skill-source"
    source_dir.mkdir()
    (source_dir / "SKILL.md").write_text(MINIMAL_SKILL_MD, encoding="utf-8")
    return client, service, source_dir, managed_root


def test_user_skill_import_enable_disable_and_audit_routes(monkeypatch, tmp_path: Path) -> None:
    """The skill router should expose a full user-skill management slice."""

    client, _service, source_dir, managed_root = _build_client(monkeypatch, tmp_path)

    import_response = client.post(
        "/skills/import",
        json={
            "source_path": str(source_dir),
            "managed_root": str(managed_root),
            "origin": "pytest",
        },
    )
    assert import_response.status_code == 200
    import_payload = import_response.json()
    assert import_payload["success"] is True
    assert import_payload["skill_id"] == "user.router.skill"
    assert import_payload["manifest"]["id"] == "user.router.skill"

    imported_response = client.get("/skills", params={"source": "imported"})
    assert imported_response.status_code == 200
    imported_skills = imported_response.json()
    assert [skill["id"] for skill in imported_skills] == ["user.router.skill"]
    assert imported_skills[0]["disabled_reason"] == "Imported skill - not yet enabled"

    enable_response = client.post("/skills/user.router.skill/enable")
    assert enable_response.status_code == 200
    assert enable_response.json() == {
        "skill_id": "user.router.skill",
        "enabled": True,
        "reason": None,
    }

    enabled_response = client.get("/skills/user.router.skill")
    assert enabled_response.status_code == 200
    assert enabled_response.json()["disabled_reason"] is None

    disable_response = client.post(
        "/skills/user.router.skill/disable",
        params={"reason": "pytest disable"},
    )
    assert disable_response.status_code == 200
    assert disable_response.json() == {
        "skill_id": "user.router.skill",
        "enabled": False,
        "reason": "pytest disable",
    }

    audit_response = client.get("/skills/audit", params={"skill_id": "user.router.skill"})
    assert audit_response.status_code == 200
    audit_events = audit_response.json()
    assert any("Imported user skill" in event["description"] for event in audit_events)
    assert any("Skill enabled" in event["description"] for event in audit_events)
    assert any("Skill disabled" in event["description"] for event in audit_events)


def test_user_skill_import_route_accepts_zip_package(monkeypatch, tmp_path: Path) -> None:
    """The import route should accept a zip package with one top-level skill directory."""

    client, _service, source_dir, managed_root = _build_client(monkeypatch, tmp_path)
    (source_dir / "prompts").mkdir()
    (source_dir / "prompts" / "main.txt").write_text("Input={{ input_text }}", encoding="utf-8")
    zip_path = tmp_path / "router-skill.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("skill-package/SKILL.md", (source_dir / "SKILL.md").read_text(encoding="utf-8"))
        archive.writestr(
            "skill-package/prompts/main.txt",
            (source_dir / "prompts" / "main.txt").read_text(encoding="utf-8"),
        )

    import_response = client.post(
        "/skills/import",
        json={
            "source_path": str(zip_path),
            "managed_root": str(managed_root),
            "origin": "pytest-zip",
        },
    )

    assert import_response.status_code == 200
    payload = import_response.json()
    assert payload["success"] is True
    assert payload["skill_id"] == "user.router.skill"
    assert payload["origin"] == "pytest-zip"


def test_user_skill_import_route_returns_machine_readable_zip_errors(monkeypatch, tmp_path: Path) -> None:
    """Invalid zip imports should return stable 422 errors."""

    client, _service, _source_dir, managed_root = _build_client(monkeypatch, tmp_path)
    bad_zip = tmp_path / "bad.zip"
    bad_zip.write_text("not a zip archive", encoding="utf-8")

    response = client.post(
        "/skills/import",
        json={"source_path": str(bad_zip), "managed_root": str(managed_root)},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["error_code"] == "INVALID_ZIP_ARCHIVE"
    assert "errors" in payload["detail"]
    assert any("valid zip archive" in error for error in payload["detail"]["errors"])


def test_user_skill_test_run_returns_structured_runtime_payload(monkeypatch, tmp_path: Path) -> None:
    """`/skills/{id}/test-run` should expose the safe runtime result shape."""

    client, _service, source_dir, managed_root = _build_client(monkeypatch, tmp_path)
    (source_dir / "prompts").mkdir()
    (source_dir / "prompts" / "main.txt").write_text("Input={{ input_text }}", encoding="utf-8")

    import_response = client.post(
        "/skills/import",
        json={
            "source_path": str(source_dir),
            "managed_root": str(managed_root),
            "origin": "pytest",
        },
    )
    assert import_response.status_code == 200
    assert client.post("/skills/user.router.skill/enable").status_code == 200

    test_response = client.post(
        "/skills/user.router.skill/test-run",
        params={"input_text": "router selected text"},
    )

    assert test_response.status_code == 200
    payload = test_response.json()
    assert payload["status"] == "success"
    assert payload["output_text"] == "Input=router selected text"
    assert payload["structured_output"]["execution_mode"] == "prompt_only"
    assert payload["audit_id"]
    assert payload["evidence_refs"] == []


def test_enabled_safe_user_skill_is_exposed_as_legacy_action(monkeypatch, tmp_path: Path) -> None:
    """Safe enabled user Skills can appear in legacy actions without enum errors."""

    client, _service, source_dir, managed_root = _build_client(monkeypatch, tmp_path)

    import_response = client.post(
        "/skills/import",
        json={
            "source_path": str(source_dir),
            "managed_root": str(managed_root),
            "origin": "pytest",
        },
    )
    assert import_response.status_code == 200
    assert client.post("/skills/user.router.skill/enable").status_code == 200

    actions_response = client.get("/actions")

    assert actions_response.status_code == 200
    actions = actions_response.json()
    custom_action = next(action for action in actions if action["skillId"] == "user.router.skill")
    assert custom_action["id"] == "skill:user.router.skill"
    assert custom_action["category"] == "other"
    assert custom_action["icon"] == "Sparkles"


def test_high_risk_user_skill_is_not_exposed_as_legacy_action(monkeypatch, tmp_path: Path) -> None:
    """User Skills with high-risk permissions should stay out of quick action surfaces."""

    client, _service, source_dir, managed_root = _build_client(monkeypatch, tmp_path)
    (source_dir / "SKILL.md").write_text(
        MINIMAL_SKILL_MD.replace("  draft.read: true", "  draft.read: true\n  network: true"),
        encoding="utf-8",
    )

    import_response = client.post(
        "/skills/import",
        json={
            "source_path": str(source_dir),
            "managed_root": str(managed_root),
            "origin": "pytest",
        },
    )
    assert import_response.status_code == 200
    assert client.post("/skills/user.router.skill/enable").status_code == 409

    actions_response = client.get("/actions")

    assert actions_response.status_code == 200
    assert all(action["skillId"] != "user.router.skill" for action in actions_response.json())


def test_high_risk_user_skill_enable_requires_approval(monkeypatch, tmp_path: Path) -> None:
    """High-risk user Skills should require a recorded approval before enabling."""

    client, service, source_dir, managed_root = _build_client(monkeypatch, tmp_path)
    (source_dir / "SKILL.md").write_text(
        MINIMAL_SKILL_MD.replace("  draft.read: true", "  draft.read: true\n  network: true"),
        encoding="utf-8",
    )

    import_response = client.post(
        "/skills/import",
        json={
            "source_path": str(source_dir),
            "managed_root": str(managed_root),
            "origin": "pytest",
        },
    )
    assert import_response.status_code == 200

    blocked_response = client.post("/skills/user.router.skill/enable")
    assert blocked_response.status_code == 409
    assert "Approval required" in blocked_response.json()["detail"]

    pending_response = client.get("/skills/approvals/pending")
    assert pending_response.status_code == 200
    pending = pending_response.json()
    assert len(pending) == 1
    assert pending[0]["capability_id"] == "user.router.skill"
    assert pending[0]["context"]["operation"] == "enable_skill"

    second_blocked_response = client.post("/skills/user.router.skill/enable")
    assert second_blocked_response.status_code == 409
    assert client.get("/skills/approvals/pending").json() == pending

    decide_response = client.post(
        f"/skills/approvals/{pending[0]['request_id']}/decide",
        json={"decision": ApprovalDecision.APPROVED.value, "reason": "pytest approval"},
    )
    assert decide_response.status_code == 200

    enabled_response = client.post("/skills/user.router.skill/enable")
    assert enabled_response.status_code == 200
    assert enabled_response.json() == {
        "skill_id": "user.router.skill",
        "enabled": True,
        "reason": None,
    }
    assert service.get_skill("user.router.skill")["disabled_reason"] is None


def test_skill_security_route_exposes_machine_readable_policy(monkeypatch, tmp_path: Path) -> None:
    """The router should expose runtime safety gates without parsing error text."""

    client, _service, source_dir, managed_root = _build_client(monkeypatch, tmp_path)
    (source_dir / "SKILL.md").write_text(
        MINIMAL_SKILL_MD.replace("  draft.read: true", "  draft.read: true\n  network: true"),
        encoding="utf-8",
    )

    import_response = client.post(
        "/skills/import",
        json={
            "source_path": str(source_dir),
            "managed_root": str(managed_root),
            "origin": "pytest",
        },
    )
    assert import_response.status_code == 200

    response = client.get("/skills/user.router.skill/security")

    assert response.status_code == 200
    payload = response.json()
    assert payload["skill_id"] == "user.router.skill"
    assert payload["risk_level"] == "high"
    assert payload["runtime_gate"] == "block_high_risk_permission"
    assert payload["runtime_executable"] is False
    assert payload["enable_requires_approval"] is True
    assert payload["high_risk_flags"] == ["network"]


def test_user_skill_import_validation_error_is_machine_readable(monkeypatch, tmp_path: Path) -> None:
    """Invalid skill packages should return stable validation errors."""

    client, _service, source_dir, managed_root = _build_client(monkeypatch, tmp_path)
    (source_dir / "SKILL.md").write_text("---\nid: INVALID ID\n---\n", encoding="utf-8")

    response = client.post(
        "/skills/import",
        json={"source_path": str(source_dir), "managed_root": str(managed_root)},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["error_code"] == "INVALID_MANIFEST"
    assert "errors" in payload["detail"]
    assert any("Invalid id" in error for error in payload["detail"]["errors"])


def test_skill_audit_route_is_not_shadowed_by_dynamic_skill_route(monkeypatch, tmp_path: Path) -> None:
    """`/skills/audit` must resolve to the audit endpoint, not `/skills/{skill_id}`."""

    client, _service, _source_dir, _managed_root = _build_client(monkeypatch, tmp_path)

    response = client.get("/skills/audit")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_skill_management_openapi_exposes_named_contract_models(monkeypatch, tmp_path: Path) -> None:
    """OpenAPI should expose stable import/toggle request and response models."""

    client, _service, _source_dir, _managed_root = _build_client(monkeypatch, tmp_path)
    schema = client.app.openapi()

    import_operation = schema["paths"]["/skills/import"]["post"]
    assert import_operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ImportUserSkillRequest"
    }
    assert import_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ImportUserSkillResponse"
    }

    enable_operation = schema["paths"]["/skills/{skill_id}/enable"]["post"]
    assert enable_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SkillToggleResponse"
    }

    test_run_operation = schema["paths"]["/skills/{skill_id}/test-run"]["post"]
    assert test_run_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SkillTestRunResponse"
    }


def test_legacy_action_result_round_trips_through_transform_result(monkeypatch, tmp_path: Path) -> None:
    """Legacy action execution should still expose a transform result payload."""

    client, _service, _source_dir, _managed_root = _build_client(monkeypatch, tmp_path)

    run_response = client.post(
        "/run_action",
        json={
            "action_id": "paraphrase_action",
            "input_text": "legacy action input",
            "scope": "selection",
            "output_mode": "plain",
        },
    )
    assert run_response.status_code == 200
    job_id = run_response.json()["jobId"]

    result_response = client.get(f"/transform_result/{job_id}")
    assert result_response.status_code == 200
    result_payload = result_response.json()
    assert result_payload["jobId"] == job_id
    assert result_payload["actionId"] == "paraphrase_action"
    assert result_payload["skillId"] == "paraphrase"
    assert result_payload["scope"] == "selection"
    assert result_payload["outputMode"] == "plain"
    assert result_payload["applied"] is True


def test_user_skill_enable_state_survives_service_restart(monkeypatch, tmp_path: Path) -> None:
    """Imported skill enabled state should be restored from managed metadata."""

    client, _service, source_dir, managed_root = _build_client(monkeypatch, tmp_path)

    import_response = client.post(
        "/skills/import",
        json={
            "source_path": str(source_dir),
            "managed_root": str(managed_root),
            "origin": "pytest",
        },
    )
    assert import_response.status_code == 200

    enable_response = client.post("/skills/user.router.skill/enable")
    assert enable_response.status_code == 200

    restarted = WritingSkillService(
        external_roots=None,
        approval_store=ApprovalStore(),
        audit_log=AuditLog(managed_root / ".audit" / "skill_audit.jsonl"),
        managed_root=managed_root,
    )
    restored = restarted.get_skill("user.router.skill")

    assert restored is not None
    assert restored["source"] == "imported"
    assert restored["disabled_reason"] is None
    assert restored["default_parameters"]["installed_path"] == str(managed_root / "user.router.skill")


def test_user_skill_audit_events_can_be_persisted_to_jsonl(tmp_path: Path) -> None:
    """AuditLog should restore append-only JSONL events after re-instantiation."""

    audit_path = tmp_path / "managed-skills" / ".audit" / "skill_audit.jsonl"
    first_log = AuditLog(audit_path)
    event = first_log.log_event(
        "capability_resolved",
        capability_id="user.router.skill",
        description="persisted audit event",
    )

    second_log = AuditLog(audit_path)
    restored = second_log.list_events()

    assert [item.event_id for item in restored] == [event.event_id]
    assert restored[0].description == "persisted audit event"
