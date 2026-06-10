"""Cross-slice regression scenarios for Evolution backend §S0-7 (Slice 8).

Plan §Slice 8 acceptance:
    - Default user workflows still work
    - Evolution can be disabled and old behavior remains available
    - Candidate review is understandable without technical knowledge
    - No promotion path can bypass backend policy

This module exercises the full capture → review → promote → rollback
lifecycle end-to-end so a regression that breaks any single slice's
contract surfaces here even if the per-slice tests pass.

These tests deliberately go through the public service / router surface
rather than poking the store directly, mirroring how a real frontend
client would drive the system.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from models.evolution import (
    CandidateMemoryType,
    CandidateSourceType,
    CandidateStatus,
)
from evolution import (
    EvolutionCandidateStore,
    EvolutionPromoter,
    EvolutionService,
    reset_evolution_service_for_tests,
)


# --- stubs ------------------------------------------------------------------

class _StubMemorySyncResult:
    def __init__(
        self,
        *,
        success: bool = True,
        available: bool = True,
        wing: str = "wing_evolution",
        room: str = "evolution-candidates",
        drawer_id: str | None = "drawer_xyz",
        duplicate: bool = False,
        reason: str | None = None,
    ) -> None:
        self.success = success
        self.available = available
        self.wing = wing
        self.room = room
        self.drawer_id = drawer_id
        self.duplicate = duplicate
        self.reason = reason


class _StubMemoryAdapter:
    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled
        self.calls: list[dict[str, Any]] = []

    def is_enabled(self) -> bool:
        return self._enabled

    def add_memory(self, wing, room, content, *, source_file, metadata, added_by):
        self.calls.append({
            "wing": wing, "room": room, "source_file": source_file,
            "metadata": metadata,
        })
        return _StubMemorySyncResult(drawer_id=f"drawer_{len(self.calls)}")


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """FastAPI TestClient with a throwaway evolution store + stub MemPalace."""

    from python_adapter_server import app  # noqa: F401
    store = EvolutionCandidateStore(db_path=str(tmp_path / "s8.sqlite3"))
    adapter = _StubMemoryAdapter()
    promoter = EvolutionPromoter(memory_adapter=adapter)
    svc = EvolutionService(store=store, promoter=promoter)
    reset_evolution_service_for_tests(svc)
    yield TestClient(app)
    reset_evolution_service_for_tests(None)


def _capture_manual(client: TestClient, **overrides) -> str:
    body = {
        "workspace_id": "ws1",
        "source_id": "src",
        "source_summary": "regression",
        "memory_type": "project_fact",
        "title": "title",
        "claim": "regression claim default",
        "future_use": "future use",
        "confidence": 0.6,
        "project_id": "p1",
    }
    body.update(overrides)
    r = client.post("/evolution/capture/manual", json=body)
    assert r.status_code == 200, r.text
    return r.json()["candidate"]["candidate_id"]


# --- §Slice 8 scenario 1: candidate review state transitions ----------------

def test_capture_to_pending_to_accepted_to_promoted_to_rolled_back(
    client: TestClient, monkeypatch,
):
    """End-to-end lifecycle: every transition in the happy path works."""

    # Promotion needs the kill switch on for this run
    monkeypatch.setattr(
        "evolution.service.load_evolution_config",
        lambda: {"promotion_enabled": True},
    )

    cid = _capture_manual(client, claim="lifecycle claim alpha")

    # S8.1: capture now lands non-blocked candidates in PENDING directly,
    # so the CAPTURED -> PENDING step is a no-op self-transition. Keep the
    # call to document the lifecycle but assert the precondition instead.
    from evolution import get_evolution_service
    svc = get_evolution_service()
    svc.mark_pending(cid)
    assert svc.get(cid).status == CandidateStatus.PENDING

    # PENDING -> ACCEPTED via router
    r = client.post(f"/evolution/candidates/{cid}/accept",
                     json={"decision_reason": "looks good"})
    assert r.status_code == 200
    assert r.json()["new_status"] == "accepted"

    # ACCEPTED -> PROMOTED_TO_MEMORY via router
    r = client.post(f"/evolution/candidates/{cid}/promote")
    assert r.status_code == 200
    promo = r.json()
    assert promo["promoted"] is True
    assert promo["target"] == "memory"
    assert promo["new_status"] == "promoted_to_memory"
    assert promo["rollback_ref"].startswith("drawer_")

    # PROMOTED_TO_MEMORY -> ROLLED_BACK via router (tombstone-first)
    r = client.post(
        f"/evolution/candidates/{cid}/rollback",
        json={"rollback_ref": "tombstone-test", "decision_reason": "decided otherwise"},
    )
    assert r.status_code == 200
    assert r.json()["new_status"] == "rolled_back"

    # Final state check
    final = svc.get(cid)
    assert final.status == CandidateStatus.ROLLED_BACK
    assert final.rollback_ref == "tombstone-test"


# --- §Slice 8 scenario 2: secret-like content blocked ------------------------

def test_secret_in_claim_marks_blocked_and_lists_under_blocked_filter(
    client: TestClient,
):
    """Plan §Fail-closed: candidates with detected secrets land in BLOCKED."""

    cid = _capture_manual(
        client,
        claim="leak: sk-proj-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        source_id="src-secret",
    )

    r = client.get("/evolution/candidates",
                    params={"workspace_id": "ws1", "status": "blocked"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(i["candidate_id"] == cid for i in items)
    blocked = next(i for i in items if i["candidate_id"] == cid)
    assert blocked["status"] == "blocked"
    assert "secret_scan:" in (blocked["decision_reason"] or "")


# --- §Slice 8 scenario 3: evidence-less domain knowledge blocked -------------

def test_evidence_less_domain_knowledge_inspiration_spark_is_dropped():
    """Plan §Fail-closed: synthesis sparks with no evidence never enter queue."""

    from evolution import extract_from_spark

    class _Spark:
        id = "s-no-evidence"
        content = "general synthesis without backing"
        spark_type = "synthesis"
        confidence = 0.6
        evidence_refs: list[dict] = []

    args = extract_from_spark(_Spark(), query="q", project_id="p")
    assert args is None


# --- §Slice 8 scenario 4: promotion path enforces backend policy -------------

def test_router_promote_requires_kill_switch_on(client: TestClient):
    """Plan §"No promotion path can bypass backend policy" — default-off
    promote returns 409 regardless of what the frontend sends."""

    cid = _capture_manual(client, claim="bypass attempt")
    from evolution import get_evolution_service
    svc = get_evolution_service()
    svc.mark_pending(cid)
    svc.accept(cid)

    # No monkeypatch — config default has promotion_enabled=false
    r = client.post(f"/evolution/candidates/{cid}/promote")
    assert r.status_code == 409
    body = r.json()
    msg = body.get("error", {}).get("message") or body.get("detail", "")
    assert "promotion_enabled" in msg
    # Candidate stays ACCEPTED — no smuggling through the API
    assert svc.get(cid).status == CandidateStatus.ACCEPTED


def test_router_promote_rejects_non_accepted(client: TestClient, monkeypatch):
    """Even with the kill switch on, only ACCEPTED candidates promote."""

    monkeypatch.setattr(
        "evolution.service.load_evolution_config",
        lambda: {"promotion_enabled": True},
    )
    cid = _capture_manual(client, claim="not accepted yet")
    # Stays in PENDING (S8.1 default) — never walked to ACCEPTED
    r = client.post(f"/evolution/candidates/{cid}/promote")
    assert r.status_code == 409
    body = r.json()
    msg = body.get("error", {}).get("message") or body.get("detail", "")
    assert "ACCEPTED" in msg


# --- §Slice 8 scenario 5: kill-switch defaults restore "old behavior" --------

def test_status_endpoint_kill_switches_default_to_safe_state(client: TestClient):
    """When operators don't enable evolution, all write paths stay off."""

    r = client.get("/evolution/status")
    assert r.status_code == 200
    body = r.json()
    # Capture is on by default (fail-closed via secret scan); the rest are
    # off until operators opt in
    assert body["candidate_capture_enabled"] is True
    assert body["recall_enabled"] is False
    assert body["promotion_enabled"] is False
    assert body["curator_enabled"] is False
    assert body["review_ui_enabled"] is False


def test_curator_default_off_is_a_no_op(client: TestClient):
    """Curator must be operator-enabled before it transitions any row."""

    cid = _capture_manual(client, claim="should-not-curator")
    from evolution import get_evolution_service
    svc = get_evolution_service()
    svc.mark_pending(cid)

    r = client.post("/evolution/curate/run")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    # PENDING candidate untouched
    assert svc.get(cid).status == CandidateStatus.PENDING


# --- §Slice 8 scenario 6: idempotency across the lifecycle -------------------

def test_double_promote_then_double_rollback_is_idempotent(
    client: TestClient, monkeypatch,
):
    monkeypatch.setattr(
        "evolution.service.load_evolution_config",
        lambda: {"promotion_enabled": True},
    )
    cid = _capture_manual(client, claim="idempotency e2e")
    from evolution import get_evolution_service
    svc = get_evolution_service()
    svc.mark_pending(cid)
    svc.accept(cid)

    # Promote twice — second is no-op
    first = client.post(f"/evolution/candidates/{cid}/promote")
    assert first.status_code == 200
    drawer = first.json()["rollback_ref"]
    second = client.post(f"/evolution/candidates/{cid}/promote")
    assert second.status_code == 200
    assert second.json()["rollback_ref"] == drawer

    # Rollback twice — second is 409 (state machine: ROLLED_BACK is terminal)
    r1 = client.post(f"/evolution/candidates/{cid}/rollback", json={})
    assert r1.status_code == 200
    r2 = client.post(f"/evolution/candidates/{cid}/rollback", json={})
    assert r2.status_code == 409
