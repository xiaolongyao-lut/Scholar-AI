"""Tests for legacy env migration (S6 / plan 2026-05-20 §6)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from credential_bindings import CredentialBindingIndex, set_credential_binding_index
from credential_store import RuntimeCredentialStore
from mcp_runtime.legacy_env_migrator import (
    LegacyRawSecret,
    SECRET_KEY_RE,
    detect_legacy_secrets,
)
from mcp_runtime.server_store import RuntimeMcpServerStore
from models.credentials import (
    CredentialCategory,
    CredentialProtocol,
    CredentialTrustSource,
    RuntimeCredentialCreate,
    RuntimeCredentialUpdate,
)
from models.mcp import (
    McpProvenance,
    McpServerConfigCreate,
    McpStdioConfig,
    McpStreamableHttpConfig,
    McpTransport,
)
from routers import credentials_router as cr_module
from routers import mcp_router as mr_module


# ---------------------------------------------------------------------------
# Unit: heuristic detector
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", [
    "OPENAI_API_KEY",
    "openai_api_key",
    "SILICONFLOW_API_KEY",
    "GITHUB_TOKEN",
    "DB_PASSWORD",
    "AUTHORIZATION",
    "BEARER_TOKEN",
    "STRIPE_SECRET",
    "WEBHOOK_SECRET",
])
def test_secret_key_re_catches_common_names(key):
    assert SECRET_KEY_RE.search(key) is not None


@pytest.mark.parametrize("key", [
    "DEBUG",
    "LOG_LEVEL",
    "TIMEOUT_SECONDS",
    "MODEL_NAME",
])
def test_secret_key_re_skips_non_secret_keys(key):
    assert SECRET_KEY_RE.search(key) is None


def test_detect_legacy_secrets_finds_stdio_env():
    result = detect_legacy_secrets(
        stdio_env={"OPENAI_API_KEY": "sk-real-secret-aaaaa", "DEBUG": "1"},
        stdio_env_refs={},
        http_headers=None,
        http_header_refs=None,
    )
    assert len(result) == 1
    assert result[0].target_env == "OPENAI_API_KEY"
    assert result[0].transport_field == "stdio.env"
    assert "sk-r" in result[0].value_masked
    assert "aaaa" in result[0].value_masked  # 4-char tail of mask
    # Raw value must not appear verbatim.
    assert "sk-real-secret-aaaaa" != result[0].value_masked


def test_detect_legacy_secrets_skips_already_in_refs():
    result = detect_legacy_secrets(
        stdio_env={"OPENAI_API_KEY": "sk-real-secret-bbbbb"},
        stdio_env_refs={"OPENAI_API_KEY": "cred_x"},
        http_headers=None,
        http_header_refs=None,
    )
    # Already covered by ref → not flagged.
    assert result == []


def test_detect_legacy_secrets_finds_http_headers():
    result = detect_legacy_secrets(
        stdio_env=None,
        stdio_env_refs=None,
        http_headers={"Authorization": "Bearer sk-real-stuff-ccccc", "X-Trace": "abc"},
        http_header_refs={},
    )
    assert len(result) == 1
    assert result[0].target_env == "Authorization"
    assert result[0].transport_field == "http.headers"


def test_detect_legacy_secrets_skips_tiny_placeholders():
    """Don't flag obvious flags like DEBUG_KEY=1 as raw secrets."""
    result = detect_legacy_secrets(
        stdio_env={"DEBUG_KEY": "1", "FEATURE_KEY": "true"},
        stdio_env_refs={},
        http_headers=None,
        http_header_refs=None,
    )
    assert result == []


# ---------------------------------------------------------------------------
# Router: GET /legacy-env + POST /migrate-env-to-refs
# ---------------------------------------------------------------------------


def _cred_create(api_key: str = "sk-test-credential-xxxxxx") -> RuntimeCredentialCreate:
    return RuntimeCredentialCreate(
        category=CredentialCategory.GENERATION,
        provider="siliconflow",
        model="Qwen2-VL-7B-Instruct",
        base_url="https://api.siliconflow.cn/v1",
        protocol=CredentialProtocol.OPENAI_CHAT_COMPLETIONS,
        api_key=api_key,
        trust_source=CredentialTrustSource.RUNTIME_USER_CONFIRMED,
    )


def _stdio_create(slug: str, env: dict[str, str]) -> McpServerConfigCreate:
    return McpServerConfigCreate(
        name=f"legacy-{slug}",
        server_slug=slug,
        transport=McpTransport.STDIO,
        stdio=McpStdioConfig(command="python", args=["-m", "x"], env=env),
        provenance=McpProvenance.RUNTIME_USER_CONFIRMED,
    )


@pytest.fixture
def server_store(tmp_path: Path) -> RuntimeMcpServerStore:
    s = RuntimeMcpServerStore(path=tmp_path / "servers.json")
    mr_module.set_mcp_server_store(s)
    yield s
    mr_module.set_mcp_server_store(None)


@pytest.fixture
def credential_store(tmp_path: Path) -> RuntimeCredentialStore:
    s = RuntimeCredentialStore(path=tmp_path / "credentials.json")
    cr_module.set_credential_store(s)
    yield s
    cr_module.set_credential_store(None)


@pytest.fixture
def binding_index() -> CredentialBindingIndex:
    idx = CredentialBindingIndex()
    set_credential_binding_index(idx)
    yield idx
    set_credential_binding_index(None)


@pytest.fixture
def client(
    server_store: RuntimeMcpServerStore,
    credential_store: RuntimeCredentialStore,
    binding_index: CredentialBindingIndex,
) -> TestClient:
    app = FastAPI()
    app.include_router(mr_module.router)
    return TestClient(app)


def test_get_legacy_env_returns_masked_entries(
    client: TestClient, server_store: RuntimeMcpServerStore
):
    s = server_store.create(_stdio_create("a", {
        "OPENAI_API_KEY": "sk-real-aaaaaaaaaaaaaaa",
        "DEBUG": "1",
    }))
    r = client.get(f"/api/mcp/servers/{s.server_id}/legacy-env")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    entry = body["entries"][0]
    assert entry["target_env"] == "OPENAI_API_KEY"
    assert entry["transport_field"] == "stdio.env"
    assert "sk-r" in entry["value_masked"]
    # Raw value must NOT leak.
    assert "sk-real-aaaaaaaaaaaaaaa" not in r.text


def test_get_legacy_env_skips_already_ref_keys(
    client: TestClient,
    server_store: RuntimeMcpServerStore,
    credential_store: RuntimeCredentialStore,
):
    cred = credential_store.create(_cred_create())
    body = _stdio_create("b", {"OPENAI_API_KEY": "sk-still-here-zzzzzz"})
    body.stdio.env_refs = {"OPENAI_API_KEY": cred.credential_id}
    s = server_store.create(body)
    r = client.get(f"/api/mcp/servers/{s.server_id}/legacy-env")
    # Already covered by ref → not flagged.
    assert r.json()["count"] == 0


def test_migrate_requires_confirm_remove_raw(
    client: TestClient,
    server_store: RuntimeMcpServerStore,
    credential_store: RuntimeCredentialStore,
):
    cred = credential_store.create(_cred_create())
    s = server_store.create(_stdio_create("c", {"OPENAI_API_KEY": "sk-x" * 5}))
    r = client.post(
        f"/api/mcp/servers/{s.server_id}/migrate-env-to-refs",
        json={"mapping": {"OPENAI_API_KEY": cred.credential_id}},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "confirm_required"


def test_migrate_happy_path_moves_to_refs_and_removes_raw(
    client: TestClient,
    server_store: RuntimeMcpServerStore,
    credential_store: RuntimeCredentialStore,
):
    cred = credential_store.create(_cred_create())
    s = server_store.create(_stdio_create("d", {
        "OPENAI_API_KEY": "sk-old-raw-aaaaaaaaaaa",
        "DEBUG": "1",
    }))
    r = client.post(
        f"/api/mcp/servers/{s.server_id}/migrate-env-to-refs",
        json={
            "mapping": {"OPENAI_API_KEY": cred.credential_id},
            "confirm_remove_raw": True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["migrated_stdio_env_keys"] == ["OPENAI_API_KEY"]

    internal = server_store.get_internal(s.server_id)
    # Raw env no longer carries the secret-shaped key.
    assert "OPENAI_API_KEY" not in internal.stdio.env
    # Non-secret env preserved.
    assert internal.stdio.env.get("DEBUG") == "1"
    # Ref points at the credential.
    assert internal.stdio.env_refs == {"OPENAI_API_KEY": cred.credential_id}


def test_migrate_rejects_unknown_credential(
    client: TestClient,
    server_store: RuntimeMcpServerStore,
):
    s = server_store.create(_stdio_create("e", {"OPENAI_API_KEY": "sk-x" * 5}))
    r = client.post(
        f"/api/mcp/servers/{s.server_id}/migrate-env-to-refs",
        json={
            "mapping": {"OPENAI_API_KEY": "cred_does_not_exist"},
            "confirm_remove_raw": True,
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "credential_not_found"


def test_migrate_rejects_disabled_credential(
    client: TestClient,
    server_store: RuntimeMcpServerStore,
    credential_store: RuntimeCredentialStore,
):
    cred = credential_store.create(_cred_create())
    credential_store.update(cred.credential_id, RuntimeCredentialUpdate(enabled=False))
    s = server_store.create(_stdio_create("f", {"OPENAI_API_KEY": "sk-x" * 5}))
    r = client.post(
        f"/api/mcp/servers/{s.server_id}/migrate-env-to-refs",
        json={
            "mapping": {"OPENAI_API_KEY": cred.credential_id},
            "confirm_remove_raw": True,
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "credential_disabled"


def test_migrate_rejects_when_no_matching_env_keys(
    client: TestClient,
    server_store: RuntimeMcpServerStore,
    credential_store: RuntimeCredentialStore,
):
    cred = credential_store.create(_cred_create())
    s = server_store.create(_stdio_create("g", {"OPENAI_API_KEY": "sk-x" * 5}))
    r = client.post(
        f"/api/mcp/servers/{s.server_id}/migrate-env-to-refs",
        json={
            "mapping": {"WRONG_KEY": cred.credential_id},
            "confirm_remove_raw": True,
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "no_matching_env_keys"


def test_migrate_404_unknown_server(
    client: TestClient, credential_store: RuntimeCredentialStore
):
    cred = credential_store.create(_cred_create())
    r = client.post(
        "/api/mcp/servers/mcp_nonexistent/migrate-env-to-refs",
        json={
            "mapping": {"OPENAI_API_KEY": cred.credential_id},
            "confirm_remove_raw": True,
        },
    )
    assert r.status_code == 404


def test_migrate_rebuilds_binding_index(
    client: TestClient,
    server_store: RuntimeMcpServerStore,
    credential_store: RuntimeCredentialStore,
    binding_index: CredentialBindingIndex,
):
    cred = credential_store.create(_cred_create())
    s = server_store.create(_stdio_create("h", {"OPENAI_API_KEY": "sk-x" * 5}))
    # Pre-migration: no bindings.
    assert binding_index.list_for("mcp_server", s.server_id) == []

    client.post(
        f"/api/mcp/servers/{s.server_id}/migrate-env-to-refs",
        json={
            "mapping": {"OPENAI_API_KEY": cred.credential_id},
            "confirm_remove_raw": True,
        },
    )
    # Post-migration: reverse index updated.
    bindings = binding_index.list_for("mcp_server", s.server_id)
    assert len(bindings) == 1
    assert bindings[0].target_env == "OPENAI_API_KEY"
    assert bindings[0].credential_id == cred.credential_id
