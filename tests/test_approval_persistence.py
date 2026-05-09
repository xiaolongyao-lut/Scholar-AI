# -*- coding: utf-8 -*-
"""Contract tests for persistent Skill approval decisions."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.skills_router as skills_router_module
from skills.approval import ApprovalDecision, ApprovalDecisionRecord, ApprovalRequest, ApprovalStore
from skills.audit import AuditLog
from skills.service import WritingSkillService


def _build_client(monkeypatch, tmp_path: Path) -> tuple[TestClient, WritingSkillService, Path]:
    """Create an isolated Skills API client with persistent approval storage."""
    managed_root = tmp_path / "managed-skills"
    approval_db = tmp_path / "approvals.sqlite3"
    service = WritingSkillService(
        external_roots=None,
        approval_store=ApprovalStore(approval_db),
        audit_log=AuditLog(),
        managed_root=managed_root,
    )
    monkeypatch.setattr(skills_router_module, "get_skill_service", lambda: service)
    app = FastAPI()
    app.include_router(skills_router_module.router)
    return TestClient(app), service, approval_db


def test_approval_store_persists_requests_and_decisions(tmp_path: Path) -> None:
    """SQLite-backed ApprovalStore should preserve state across instances."""
    sqlite_path = tmp_path / "skill-approvals.sqlite3"
    first_store = ApprovalStore(sqlite_path)
    request = ApprovalRequest(
        request_id="appr_test",
        capability_id="user.skill",
        capability_name="User Skill",
        reason="Needs high-risk permission",
        context={"permission": "network"},
    )
    first_store.submit_approval_request(request)
    first_store.record_decision(
        ApprovalDecisionRecord(
            request_id="appr_test",
            decision=ApprovalDecision.DEFERRED.value,
            user_id="owner",
            reason="Review later",
        )
    )

    second_store = ApprovalStore(sqlite_path)

    restored = second_store.get_request("appr_test")
    assert restored is not None
    assert restored.capability_id == "user.skill"
    assert restored.context == {"permission": "network"}
    assert [item.request_id for item in second_store.get_pending_requests()] == ["appr_test"]
    latest = second_store.get_latest_decision("appr_test")
    assert latest is not None
    assert latest.decision == ApprovalDecision.DEFERRED.value

    second_store.record_decision(
        ApprovalDecisionRecord(
            request_id="appr_test",
            decision=ApprovalDecision.APPROVED.value,
            user_id="owner",
        )
    )
    third_store = ApprovalStore(sqlite_path)
    assert third_store.get_pending_requests() == []
    assert third_store.get_latest_decision("appr_test").decision == ApprovalDecision.APPROVED.value


def test_approval_router_contract_round_trip(monkeypatch, tmp_path: Path) -> None:
    """Skills API should expose create, pending, detail, and decide approval routes."""
    client, service, _approval_db = _build_client(monkeypatch, tmp_path)

    create_response = client.post(
        "/skills/approvals/requests",
        json={
            "capability_id": "user.router.approval",
            "capability_name": "Router Approval Skill",
            "reason": "Enable network permission",
            "context": {"permission": "network"},
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["request_id"].startswith("appr_")
    assert created["capability_id"] == "user.router.approval"
    assert created["context"] == {"permission": "network"}

    pending_response = client.get("/skills/approvals/pending")
    assert pending_response.status_code == 200
    assert [item["request_id"] for item in pending_response.json()] == [created["request_id"]]

    decide_response = client.post(
        f"/skills/approvals/{created['request_id']}/decide",
        json={
            "decision": "approved",
            "user_id": "owner",
            "reason": "Approved for local test",
        },
    )
    assert decide_response.status_code == 200
    assert decide_response.json()["decision"] == "approved"

    detail_response = client.get(f"/skills/approvals/{created['request_id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["request"]["request_id"] == created["request_id"]
    assert detail["latest_decision"]["decision"] == "approved"
    assert len(detail["decisions"]) == 1

    assert client.get("/skills/approvals/pending").json() == []
    audit_events = service.list_audit_events(skill_id="user.router.approval", limit=20)
    assert any(event["event_type"] == "approval_requested" for event in audit_events)
    assert any(event["event_type"] == "approval_decided" for event in audit_events)


def test_approval_router_rejects_invalid_or_missing_decisions(monkeypatch, tmp_path: Path) -> None:
    """Invalid decisions should be machine-readable failures, not silent no-ops."""
    client, _service, _approval_db = _build_client(monkeypatch, tmp_path)

    missing_response = client.post(
        "/skills/approvals/appr_missing/decide",
        json={"decision": "approved"},
    )
    assert missing_response.status_code == 404

    create_response = client.post(
        "/skills/approvals/requests",
        json={
            "capability_id": "user.router.invalid",
            "capability_name": "Invalid Approval Skill",
            "reason": "Needs decision validation",
        },
    )
    request_id = create_response.json()["request_id"]

    invalid_response = client.post(
        f"/skills/approvals/{request_id}/decide",
        json={"decision": "maybe"},
    )
    assert invalid_response.status_code == 400
    assert "Unsupported approval decision" in invalid_response.json()["detail"]


def test_approval_openapi_exposes_named_contract_models(monkeypatch, tmp_path: Path) -> None:
    """Approval endpoints should use stable named OpenAPI schemas."""
    client, _service, _approval_db = _build_client(monkeypatch, tmp_path)
    schema = client.app.openapi()

    create_operation = schema["paths"]["/skills/approvals/requests"]["post"]
    assert create_operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SkillApprovalRequestCreate"
    }
    assert create_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SkillApprovalRequestPayload"
    }

    decide_operation = schema["paths"]["/skills/approvals/{request_id}/decide"]["post"]
    assert decide_operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SkillApprovalDecisionCreate"
    }
    assert decide_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SkillApprovalDecisionPayload"
    }

    detail_operation = schema["paths"]["/skills/approvals/{request_id}"]["get"]
    assert detail_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SkillApprovalDetailPayload"
    }
