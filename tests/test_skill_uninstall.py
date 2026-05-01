# -*- coding: utf-8 -*-
"""Contract tests for managed user skill uninstall and rollback APIs."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.skills_router as skills_router_module
from skills.audit import AuditLog
from skills.approval import ApprovalStore
from skills.service import WritingSkillService


SKILL_TEMPLATE = """---
id: {skill_id}
name: {name}
version: {version}
kind: transform
description: {description}
entry_mode: manual
ui_visibility: skill_assisted
supported_scopes: [selection]
permissions:
  draft.read: true
script_policy:
  has_scripts: false
  safe_to_execute: false
---

# {name}
"""


def _write_skill_package(source_dir: Path, *, skill_id: str, version: str, name: str) -> None:
    """Write a minimal user skill package with deterministic prompt content."""

    if not skill_id:
        raise ValueError("skill_id must not be empty")
    if not version:
        raise ValueError("version must not be empty")
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "SKILL.md").write_text(
        SKILL_TEMPLATE.format(
            skill_id=skill_id,
            name=name,
            version=version,
            description=f"{name} package for uninstall tests.",
        ),
        encoding="utf-8",
    )
    prompts_dir = source_dir / "prompts"
    prompts_dir.mkdir(exist_ok=True)
    (prompts_dir / "main.txt").write_text(f"{name} v{version}: {{{{ input_text }}}}", encoding="utf-8")


def _build_client(monkeypatch, tmp_path: Path) -> tuple[TestClient, WritingSkillService, Path, Path]:
    """Create an isolated FastAPI client and skill service for route tests."""

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
    _write_skill_package(
        source_dir,
        skill_id="user.uninstall.skill",
        version="1.0.0",
        name="Uninstall Skill",
    )
    return client, service, source_dir, managed_root


def _import_default_skill(client: TestClient, source_dir: Path, managed_root: Path) -> dict[str, object]:
    """Import the default uninstall test skill and return the API payload."""

    response = client.post(
        "/skills/import",
        json={
            "source_path": str(source_dir),
            "managed_root": str(managed_root),
            "origin": "pytest",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    return payload


def test_user_skill_uninstall_creates_backup_and_removes_registry_entry(monkeypatch, tmp_path: Path) -> None:
    """Deleting a managed user skill should preserve a rollback copy before removal."""

    client, service, source_dir, managed_root = _build_client(monkeypatch, tmp_path)
    _import_default_skill(client, source_dir, managed_root)

    response = client.delete("/skills/user.uninstall.skill")

    assert response.status_code == 200
    payload = response.json()
    backup_path = Path(payload["backup_path"])
    removed_path = Path(payload["removed_path"])
    assert payload["skill_id"] == "user.uninstall.skill"
    assert payload["uninstalled"] is True
    assert payload["dry_run"] is False
    assert backup_path.exists()
    assert (backup_path / "SKILL.md").exists()
    assert not removed_path.exists()
    assert service.get_skill("user.uninstall.skill") is None
    assert client.get("/skills/user.uninstall.skill").status_code == 404

    audit_response = client.get("/skills/audit", params={"skill_id": "user.uninstall.skill"})
    assert audit_response.status_code == 200
    assert any("Skill uninstalled" in event["description"] for event in audit_response.json())


def test_user_skill_uninstall_dry_run_does_not_touch_files(monkeypatch, tmp_path: Path) -> None:
    """Dry-run uninstall should report paths without mutating registry or disk."""

    client, service, source_dir, managed_root = _build_client(monkeypatch, tmp_path)
    _import_default_skill(client, source_dir, managed_root)

    response = client.delete("/skills/user.uninstall.skill", params={"dry_run": True})

    assert response.status_code == 200
    payload = response.json()
    assert payload["uninstalled"] is False
    assert payload["dry_run"] is True
    assert Path(payload["removed_path"]).exists()
    assert not Path(payload["backup_path"]).exists()
    assert service.get_skill("user.uninstall.skill") is not None


def test_builtin_skill_uninstall_is_forbidden(monkeypatch, tmp_path: Path) -> None:
    """Builtin capabilities are base features and must not be removable via user APIs."""

    client, _service, _source_dir, _managed_root = _build_client(monkeypatch, tmp_path)

    response = client.delete("/skills/paraphrase")

    assert response.status_code == 403
    assert "Builtin skills cannot be uninstalled" in response.json()["detail"]


def test_rollback_restores_latest_user_skill_backup(monkeypatch, tmp_path: Path) -> None:
    """Rollback without an explicit path should restore the latest normal snapshot."""

    client, service, source_dir, managed_root = _build_client(monkeypatch, tmp_path)
    _import_default_skill(client, source_dir, managed_root)
    assert client.post("/skills/user.uninstall.skill/enable").status_code == 200
    uninstall_response = client.delete("/skills/user.uninstall.skill")
    assert uninstall_response.status_code == 200

    rollback_response = client.post("/skills/user.uninstall.skill/rollback", json={})

    assert rollback_response.status_code == 200
    payload = rollback_response.json()
    restored_path = Path(payload["restored_path"])
    assert payload["rolled_back"] is True
    assert restored_path.exists()
    assert restored_path == managed_root / "user.uninstall.skill"
    restored_skill = service.get_skill("user.uninstall.skill")
    assert restored_skill is not None
    assert restored_skill["disabled_reason"] is None

    test_run_response = client.post(
        "/skills/user.uninstall.skill/test-run",
        params={"input_text": "restored input"},
    )
    assert test_run_response.status_code == 200
    assert test_run_response.json()["output_text"] == "Uninstall Skill v1.0.0: restored input"


def test_rollback_can_restore_explicit_older_backup(monkeypatch, tmp_path: Path) -> None:
    """Explicit backup paths should allow rollback to a selected prior package version."""

    client, service, source_dir, managed_root = _build_client(monkeypatch, tmp_path)
    _import_default_skill(client, source_dir, managed_root)
    first_backup = Path(client.delete("/skills/user.uninstall.skill").json()["backup_path"])
    assert client.post(
        "/skills/user.uninstall.skill/rollback",
        json={"backup_path": str(first_backup)},
    ).status_code == 200

    _write_skill_package(
        source_dir,
        skill_id="user.uninstall.skill",
        version="2.0.0",
        name="Uninstall Skill Updated",
    )
    _import_default_skill(client, source_dir, managed_root)
    second_backup = Path(client.delete("/skills/user.uninstall.skill").json()["backup_path"])
    assert second_backup != first_backup

    response = client.post(
        "/skills/user.uninstall.skill/rollback",
        json={"backup_path": str(first_backup)},
    )

    assert response.status_code == 200
    restored = service.get_skill("user.uninstall.skill")
    assert restored is not None
    assert restored["version"] == "1.0.0"
    assert Path(response.json()["backup_path"]) == first_backup


def test_rollback_rejects_backup_path_outside_managed_snapshot_root(monkeypatch, tmp_path: Path) -> None:
    """Rollback input paths must stay inside the managed rollback snapshot directory."""

    client, _service, _source_dir, _managed_root = _build_client(monkeypatch, tmp_path)
    outside = tmp_path / "outside-backup"
    _write_skill_package(
        outside,
        skill_id="user.uninstall.skill",
        version="1.0.0",
        name="Outside Backup",
    )

    response = client.post(
        "/skills/user.uninstall.skill/rollback",
        json={"backup_path": str(outside)},
    )

    assert response.status_code == 400
    assert "managed rollback root" in response.json()["detail"]


def test_rollback_rejects_snapshot_with_mismatched_manifest_id(monkeypatch, tmp_path: Path) -> None:
    """A snapshot for one skill id must not be restored into another skill directory."""

    client, _service, _source_dir, managed_root = _build_client(monkeypatch, tmp_path)
    mismatched = managed_root / ".rollback_snapshots" / "user.uninstall.skill-mismatch"
    _write_skill_package(
        mismatched,
        skill_id="user.other.skill",
        version="1.0.0",
        name="Other Skill",
    )

    response = client.post(
        "/skills/user.uninstall.skill/rollback",
        json={"backup_path": str(mismatched)},
    )

    assert response.status_code == 400
    assert "skill id mismatch" in response.json()["detail"]


def test_uninstall_and_rollback_openapi_expose_named_contract_models(monkeypatch, tmp_path: Path) -> None:
    """OpenAPI should expose stable named models for uninstall and rollback clients."""

    client, _service, _source_dir, _managed_root = _build_client(monkeypatch, tmp_path)
    schema = client.app.openapi()

    delete_operation = schema["paths"]["/skills/{skill_id}"]["delete"]
    assert delete_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SkillUninstallResponse"
    }

    rollback_operation = schema["paths"]["/skills/{skill_id}/rollback"]["post"]
    assert rollback_operation["requestBody"]["content"]["application/json"]["schema"]["anyOf"] == [
        {"$ref": "#/components/schemas/SkillRollbackRequest"},
        {"type": "null"},
    ]
    assert rollback_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SkillRollbackResponse"
    }
