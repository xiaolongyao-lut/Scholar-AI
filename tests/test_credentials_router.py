"""Tests for credentials_router (Slice A3 / DEC-002b / DEC-002c).

Covers:
  - GET / POST / PUT / DELETE /api/credentials CRUD
  - POST /api/credentials/{id}/test:
      * untrusted_custom -> skipped (no probe)
      * official_provider with mismatched host -> rejected (no probe)
      * official_provider with matched host + DNS rebind to private -> rejected
      * official_provider with matched host + safe DNS -> probe runs (mocked)
      * one-shot trust_source_override
  - 404 paths for missing credentials
  - Public payloads never leak api_key
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from credential_store import RuntimeCredentialStore
from routers import credentials_router as cr_module


DUMMY_ANTHROPIC_KEY = "test-ant-router-key-1234567890ABCDEF"
DUMMY_OPENAI_KEY = "test-openai-router-key-1234567890ABCDEF"
DUMMY_EMBEDDING_KEY = "test-embedding-router-key-1234567890ABC"


@pytest.fixture()
def store(tmp_path: Path) -> RuntimeCredentialStore:
    s = RuntimeCredentialStore(path=tmp_path / "runtime_credentials.json")
    cr_module.set_credential_store(s)
    yield s
    cr_module.set_credential_store(None)


@pytest.fixture()
def client(store: RuntimeCredentialStore) -> TestClient:
    app = FastAPI()
    app.include_router(cr_module.router)
    return TestClient(app)


def _create_body(
    *,
    api_key: str = DUMMY_ANTHROPIC_KEY,
    base_url: str = "https://anyrouter.top/v1",
    provider: str = "AnyRouter",
    model: str = "claude-opus-4-7",
    protocol: str = "anthropic_messages",
    trust_source: str = "runtime_untrusted_custom",
    category: str = "generation",
) -> dict:
    return {
        "category": category,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "protocol": protocol,
        "api_key": api_key,
        "trust_source": trust_source,
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_list_empty(client: TestClient) -> None:
    r = client.get("/api/credentials")
    assert r.status_code == 200
    assert r.json() == []


def test_create_returns_masked(client: TestClient) -> None:
    r = client.post("/api/credentials", json=_create_body())
    assert r.status_code == 200, r.text
    pub = r.json()
    assert pub["credential_id"].startswith("cred_")
    assert pub["has_api_key"] is True
    assert DUMMY_ANTHROPIC_KEY not in r.text
    assert pub["api_key_masked"].startswith("test")
    assert pub["api_key_masked"].endswith("CDEF")


def test_get_missing_returns_404(client: TestClient) -> None:
    r = client.get("/api/credentials/cred_nonexistent")
    assert r.status_code == 404


def test_get_existing_returns_masked(client: TestClient) -> None:
    pub = client.post("/api/credentials", json=_create_body()).json()
    r = client.get(f"/api/credentials/{pub['credential_id']}")
    assert r.status_code == 200
    assert DUMMY_ANTHROPIC_KEY not in r.text


def test_update_can_rotate_key(client: TestClient) -> None:
    pub = client.post("/api/credentials", json=_create_body()).json()
    new_key = "test-ant-rotated-router-key-1234567890XYZ"
    r = client.put(
        f"/api/credentials/{pub['credential_id']}",
        json={"api_key": new_key},
    )
    assert r.status_code == 200
    pub2 = r.json()
    assert pub2["fingerprint"] != pub["fingerprint"]
    assert new_key not in r.text


def test_update_missing_returns_404(client: TestClient) -> None:
    r = client.put(
        "/api/credentials/cred_nonexistent",
        json={"notes": "anything"},
    )
    assert r.status_code == 404


def test_delete(client: TestClient) -> None:
    pub = client.post("/api/credentials", json=_create_body()).json()
    r = client.delete(f"/api/credentials/{pub['credential_id']}")
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    # Second delete -> 404
    r2 = client.delete(f"/api/credentials/{pub['credential_id']}")
    assert r2.status_code == 404


def test_filter_by_category(client: TestClient) -> None:
    client.post("/api/credentials", json=_create_body())
    client.post(
        "/api/credentials",
        json=_create_body(
            api_key=DUMMY_EMBEDDING_KEY,
            provider="SiliconFlow",
            model="bge-m3",
            base_url="https://api.siliconflow.cn/v1",
            protocol="embeddings",
            category="embedding",
        ),
    )
    r = client.get("/api/credentials", params={"category": "generation"})
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["category"] == "generation"


# ---------------------------------------------------------------------------
# Test endpoint — policy gate (no network)
# ---------------------------------------------------------------------------


def test_endpoint_test_untrusted_returns_skipped(client: TestClient) -> None:
    pub = client.post(
        "/api/credentials",
        json=_create_body(trust_source="runtime_untrusted_custom"),
    ).json()
    r = client.post(f"/api/credentials/{pub['credential_id']}/test")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "skipped"
    assert body["probed"] is False
    assert "untrusted" in body["reason"]


def test_endpoint_test_official_host_mismatch_rejected(client: TestClient) -> None:
    pub = client.post(
        "/api/credentials",
        json=_create_body(
            base_url="https://attacker.example.com/v1",
            trust_source="official_provider",
        ),
    ).json()
    r = client.post(f"/api/credentials/{pub['credential_id']}/test")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "rejected"
    assert "host_mismatch" in body["reason"]
    assert body["probed"] is False


def test_endpoint_test_dns_rebinding_to_private_rejected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "provider_endpoint_policy.resolve_host",
        lambda host: ["192.168.1.1"],
    )
    pub = client.post(
        "/api/credentials",
        json=_create_body(
            api_key=DUMMY_OPENAI_KEY,
            base_url="https://api.openai.com/v1",
            provider="OpenAI",
            model="gpt-4o",
            protocol="openai_chat_completions",
            trust_source="official_provider",
        ),
    ).json()
    r = client.post(f"/api/credentials/{pub['credential_id']}/test")
    body = r.json()
    assert body["status"] == "rejected"
    assert "unsafe_ip" in body["reason"]
    # Must not have probed
    assert body["probed"] is False
    # Decision log MUST never carry the api_key
    assert DUMMY_OPENAI_KEY not in r.text


def test_endpoint_test_404_for_missing_credential(client: TestClient) -> None:
    r = client.post("/api/credentials/cred_nonexistent/test")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Test endpoint — probe (network mocked)
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeClient:
    def __init__(self, *args, **kwargs) -> None:
        self._head_status = 200
        self._get_status = 200
        self._captured_headers: dict[str, str] | None = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def head(self, url, headers=None):
        self._captured_headers = headers
        return _FakeResp(self._head_status)

    def get(self, url, headers=None):
        self._captured_headers = headers
        return _FakeResp(self._get_status)


def test_endpoint_test_probe_runs_after_policy_pass(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "provider_endpoint_policy.resolve_host",
        lambda host: ["104.18.6.192"],
    )
    pub = client.post(
        "/api/credentials",
        json=_create_body(
            api_key=DUMMY_OPENAI_KEY,
            base_url="https://api.openai.com/v1",
            provider="OpenAI",
            model="gpt-4o",
            protocol="openai_chat_completions",
            trust_source="official_provider",
        ),
    ).json()
    fake = _FakeClient()

    def fake_client_factory(*args, **kwargs):
        return fake

    with patch("httpx.Client", side_effect=fake_client_factory):
        r = client.post(f"/api/credentials/{pub['credential_id']}/test")
    body = r.json()
    assert body["status"] == "ok", body
    assert body["probe"]["probed"] is True
    assert body["probe"]["status_code"] == 200
    # The probe MUST have built the auth header AFTER policy validation
    assert fake._captured_headers is not None
    assert fake._captured_headers.get("Authorization") == f"Bearer {DUMMY_OPENAI_KEY}"
    # But the API response body MUST NOT include the raw key
    assert DUMMY_OPENAI_KEY not in r.text


def test_endpoint_test_probe_falls_back_to_get_on_405(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "provider_endpoint_policy.resolve_host",
        lambda host: ["104.18.6.192"],
    )
    pub = client.post(
        "/api/credentials",
        json=_create_body(
            api_key=DUMMY_OPENAI_KEY,
            base_url="https://api.openai.com/v1",
            provider="OpenAI",
            model="gpt-4o",
            protocol="openai_chat_completions",
            trust_source="official_provider",
        ),
    ).json()
    fake = _FakeClient()
    fake._head_status = 405
    fake._get_status = 401  # auth failure but reachable -> still "reachable"

    with patch("httpx.Client", side_effect=lambda *a, **k: fake):
        r = client.post(f"/api/credentials/{pub['credential_id']}/test")
    body = r.json()
    assert body["probe"]["method"] == "GET"
    assert body["probe"]["status_code"] == 401
    assert body["probe"]["status_class"] == "4xx"


def test_endpoint_test_probe_uses_anthropic_header_for_anthropic_protocol(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "provider_endpoint_policy.resolve_host",
        lambda host: ["104.18.6.192"],
    )
    pub = client.post(
        "/api/credentials",
        json=_create_body(
            api_key=DUMMY_ANTHROPIC_KEY,
            base_url="https://api.anthropic.com",
            provider="Anthropic",
            model="claude-opus-4-7",
            protocol="anthropic_messages",
            trust_source="official_provider",
        ),
    ).json()
    fake = _FakeClient()

    with patch("httpx.Client", side_effect=lambda *a, **k: fake):
        r = client.post(f"/api/credentials/{pub['credential_id']}/test")
    assert r.status_code == 200
    assert fake._captured_headers is not None
    assert fake._captured_headers.get("x-api-key") == DUMMY_ANTHROPIC_KEY
    assert "Authorization" not in fake._captured_headers
    # Raw key never appears in response
    assert DUMMY_ANTHROPIC_KEY not in r.text


def test_endpoint_test_one_shot_trust_override(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per DEC-002c: override applies to this test only and is NOT persisted."""
    monkeypatch.setattr(
        "provider_endpoint_policy.resolve_host",
        lambda host: ["104.18.6.192"],
    )
    pub = client.post(
        "/api/credentials",
        json=_create_body(
            api_key=DUMMY_ANTHROPIC_KEY,
            base_url="https://windhub.cc/v1",
            provider="WindHub",
            model="claude-opus-4-7",
            protocol="anthropic_messages",
            trust_source="runtime_untrusted_custom",
        ),
    ).json()
    fake = _FakeClient()
    with patch("httpx.Client", side_effect=lambda *a, **k: fake):
        r = client.post(
            f"/api/credentials/{pub['credential_id']}/test",
            json={"trust_source_override": "runtime_user_confirmed"},
        )
    body = r.json()
    assert body["status"] == "ok", body
    # Reload the persisted store: trust_source must be unchanged
    persisted = client.get(f"/api/credentials/{pub['credential_id']}").json()
    assert persisted["trust_source"] == "runtime_untrusted_custom"


def test_endpoint_test_unknown_override_returns_400(client: TestClient) -> None:
    pub = client.post(
        "/api/credentials",
        json=_create_body(),
    ).json()
    r = client.post(
        f"/api/credentials/{pub['credential_id']}/test",
        json={"trust_source_override": "totally_made_up"},
    )
    assert r.status_code == 400


def test_endpoint_test_probe_timeout_marked_unreachable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    monkeypatch.setattr(
        "provider_endpoint_policy.resolve_host",
        lambda host: ["104.18.6.192"],
    )
    pub = client.post(
        "/api/credentials",
        json=_create_body(
            api_key=DUMMY_OPENAI_KEY,
            base_url="https://api.openai.com/v1",
            provider="OpenAI",
            model="gpt-4o",
            protocol="openai_chat_completions",
            trust_source="official_provider",
        ),
    ).json()

    class _TimeoutClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def head(self, url, headers=None):
            raise httpx.TimeoutException("simulated")

    with patch("httpx.Client", side_effect=lambda *a, **k: _TimeoutClient()):
        r = client.post(f"/api/credentials/{pub['credential_id']}/test")
    body = r.json()
    assert body["status"] == "probe_failed"
    assert body["probe"]["error"] == "timeout"
    assert body["probe"]["reachable"] is False


# ---------------------------------------------------------------------------
# File-on-disk invariants
# ---------------------------------------------------------------------------


def test_create_persists_secret_to_disk_only(
    client: TestClient,
    store: RuntimeCredentialStore,
) -> None:
    pub = client.post("/api/credentials", json=_create_body()).json()
    raw_disk = store.path.read_text(encoding="utf-8")
    assert DUMMY_ANTHROPIC_KEY in raw_disk, "raw credentials file MUST hold the secret"
    # API never returned it
    listing = client.get("/api/credentials").text
    assert DUMMY_ANTHROPIC_KEY not in listing
