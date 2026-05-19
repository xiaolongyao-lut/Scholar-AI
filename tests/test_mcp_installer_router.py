"""Tests for the MCP installer router + template_installer + scan_registry
(S3 / plan 2026-05-20 §A2-A3 + Locked Revisions M5-M7).

End-to-end coverage through TestClient so we exercise the same code path the
frontend wizard would hit, with a mocked catalog (probe) and tmp-path-backed
stores.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from credential_bindings import CredentialBindingIndex
from credential_store import RuntimeCredentialStore
from mcp_runtime.client_manager import McpServerLaunchError
from mcp_runtime.scan_registry import (
    McpScanRegistry,
    ScanExpiredError,
    ScanNotFoundError,
)
from mcp_runtime.server_store import RuntimeMcpServerStore
from mcp_runtime.template_installer import (
    InstallCandidateMismatchError,
    InstallCredentialDisabledError,
    InstallCredentialMissingError,
    InstallScanExpiredError,
    InstallSlugConflictError,
    McpTemplateInstaller,
)
from models.credentials import (
    CredentialCategory,
    CredentialProtocol,
    CredentialTrustSource,
    RuntimeCredentialCreate,
    RuntimeCredentialUpdate,
)
from models.mcp_installation import (
    McpLaunchCandidate,
    McpPackageScanResult,
    McpScanConfidence,
    SCAN_ID_TTL_SECONDS,
    compute_launch_candidate_sha,
    compute_scan_expiry,
    generate_scan_id,
)
from routers import mcp_installer_router as installer_router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_credential_create(api_key: str = "sk-test-key-aaaaaaaaaaaaaaaa") -> RuntimeCredentialCreate:
    return RuntimeCredentialCreate(
        category=CredentialCategory.GENERATION,
        provider="siliconflow",
        model="Qwen2-VL-7B-Instruct",
        base_url="https://api.siliconflow.cn/v1",
        protocol=CredentialProtocol.OPENAI_CHAT_COMPLETIONS,
        api_key=api_key,
        trust_source=CredentialTrustSource.RUNTIME_USER_CONFIRMED,
    )


@pytest.fixture
def credential_store(tmp_path: Path) -> RuntimeCredentialStore:
    return RuntimeCredentialStore(path=tmp_path / "credentials.json")


@pytest.fixture
def server_store(tmp_path: Path) -> RuntimeMcpServerStore:
    return RuntimeMcpServerStore(path=tmp_path / "servers.json")


@pytest.fixture
def binding_index() -> CredentialBindingIndex:
    return CredentialBindingIndex()


@pytest.fixture
def scan_registry() -> McpScanRegistry:
    return McpScanRegistry()


@pytest.fixture
def mock_catalog() -> AsyncMock:
    catalog = AsyncMock()
    catalog.get_tools = AsyncMock(return_value=[])
    catalog.invalidate = AsyncMock(return_value=None)
    catalog.fingerprint = AsyncMock(return_value="fp_test")
    return catalog


@pytest.fixture
def installer(
    server_store: RuntimeMcpServerStore,
    scan_registry: McpScanRegistry,
    credential_store: RuntimeCredentialStore,
    binding_index: CredentialBindingIndex,
    mock_catalog: AsyncMock,
    tmp_path: Path,
) -> McpTemplateInstaller:
    return McpTemplateInstaller(
        server_store=server_store,
        scan_registry=scan_registry,
        credential_store=credential_store,
        tool_catalog=mock_catalog,
        binding_index=binding_index,
        install_root=tmp_path / "mcp_installs",
    )


@pytest.fixture
def client(
    installer: McpTemplateInstaller,
    scan_registry: McpScanRegistry,
) -> TestClient:
    installer_router.set_router_installer(installer)
    installer_router.set_router_scan_registry(scan_registry)
    app = FastAPI()
    app.include_router(installer_router.router)
    yield TestClient(app)
    installer_router.set_router_installer(None)
    installer_router.set_router_scan_registry(None)
    installer_router.set_router_scanner(None)


def _make_scan(
    *,
    source_path: Path,
    candidate_command: str = "python",
    candidate_args: list[str] | None = None,
) -> McpPackageScanResult:
    """Build a McpPackageScanResult with one launch candidate."""
    args = candidate_args if candidate_args is not None else ["-m", "lit_mcp_test.server"]
    sha = compute_launch_candidate_sha(candidate_command, args, ".")
    candidate = McpLaunchCandidate(
        command=candidate_command,
        args=args,
        cwd=".",
        confidence=McpScanConfidence.HIGH,
        source="literature-mcp.json",
        sha=sha,
    )
    return McpPackageScanResult(
        scan_id=generate_scan_id(),
        source_path=str(source_path),
        package_id="lit-mcp-test",
        display_name="Test MCP",
        confidence=McpScanConfidence.HIGH,
        transport="stdio",
        launch_candidates=[candidate],
        expires_at=compute_scan_expiry(),
    )


# ===========================================================================
# Scan registry
# ===========================================================================


def test_registry_register_and_get(scan_registry: McpScanRegistry, tmp_path: Path):
    scan = _make_scan(source_path=tmp_path)
    scan_registry.register(scan)
    fetched = scan_registry.get(scan.scan_id)
    assert fetched.scan_id == scan.scan_id


def test_registry_unknown_id_raises_not_found(scan_registry: McpScanRegistry):
    with pytest.raises(ScanNotFoundError):
        scan_registry.get("scan_does_not_exist")


def test_registry_expired_raises_expired_and_evicts(
    scan_registry: McpScanRegistry, tmp_path: Path
):
    scan = _make_scan(source_path=tmp_path)
    # Replace expires_at with a past timestamp.
    past = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat(timespec="seconds")
    expired_scan = scan.model_copy(update={"expires_at": past})
    scan_registry.register(expired_scan)
    with pytest.raises(ScanExpiredError):
        scan_registry.get(expired_scan.scan_id)
    # Side effect: evicted, second lookup is not_found.
    with pytest.raises(ScanNotFoundError):
        scan_registry.get(expired_scan.scan_id)


def test_registry_purge_expired_counts(scan_registry: McpScanRegistry, tmp_path: Path):
    past = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat(timespec="seconds")
    for _ in range(3):
        scan = _make_scan(source_path=tmp_path).model_copy(update={"expires_at": past})
        scan_registry.register(scan)
    fresh = _make_scan(source_path=tmp_path)
    scan_registry.register(fresh)
    assert scan_registry.size() == 4
    removed = scan_registry.purge_expired()
    assert removed == 3
    assert scan_registry.size() == 1


# ===========================================================================
# Template installer — happy path + failure modes
# ===========================================================================


def _await(coro):
    """Run an async coroutine to completion with a fresh event loop.

    Using ``asyncio.run`` (not ``get_event_loop``) avoids state pollution
    when other tests in the suite close or replace the default loop.
    """
    return asyncio.run(coro)


def test_install_happy_path_without_probe(
    installer: McpTemplateInstaller,
    scan_registry: McpScanRegistry,
    credential_store: RuntimeCredentialStore,
    binding_index: CredentialBindingIndex,
    server_store: RuntimeMcpServerStore,
    tmp_path: Path,
):
    cred = credential_store.create(_make_credential_create())
    scan = _make_scan(source_path=tmp_path)
    scan_registry.register(scan)

    result = _await(installer.install(
        scan_id=scan.scan_id,
        launch_candidate_sha=scan.launch_candidates[0].sha,
        server_slug="test_mcp",
        display_name="Test MCP",
        config_values={"DEBUG": "1"},
        credential_bindings={"SILICONFLOW_API_KEY": cred.credential_id},
        trust_to_probe=False,
    ))

    # Server created; approval state stays at registered (no probe).
    assert result.approval_state == "registered"
    assert result.probe.status == "skipped_untrusted"

    # env_refs persisted on the server.
    internal = server_store.get_internal(result.server.server_id)
    assert internal.stdio.env_refs == {"SILICONFLOW_API_KEY": cred.credential_id}
    assert internal.stdio.env == {"DEBUG": "1"}

    # Public view masks env but passes refs verbatim.
    public = server_store.get_public(result.server.server_id)
    assert public.stdio.env_refs == {"SILICONFLOW_API_KEY": cred.credential_id}

    # Binding index rebuilt.
    bindings = binding_index.list_for("mcp_server", result.server.server_id)
    assert len(bindings) == 1
    assert bindings[0].credential_id == cred.credential_id

    # Install dir + sidecar exist.
    install_dir = Path(result.install_dir)
    assert install_dir.exists()
    record_path = install_dir / "install_record.json"
    assert record_path.is_file()
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["server_id"] == result.server.server_id
    assert record["absolute_cwd"] == str(tmp_path.resolve())
    assert record["credential_env_names"] == ["SILICONFLOW_API_KEY"]


def test_install_with_trust_probe_advances_to_catalog_reviewed(
    installer: McpTemplateInstaller,
    scan_registry: McpScanRegistry,
    credential_store: RuntimeCredentialStore,
    server_store: RuntimeMcpServerStore,
    mock_catalog: AsyncMock,
    tmp_path: Path,
):
    cred = credential_store.create(_make_credential_create())
    scan = _make_scan(source_path=tmp_path)
    scan_registry.register(scan)

    # Mock probe returns 1 tool.
    from models.mcp import McpToolCapability, McpToolDescriptor

    mock_catalog.get_tools.return_value = [
        McpToolDescriptor(name="echo", description="", input_schema={},
                          capability=McpToolCapability.READ)
    ]

    result = _await(installer.install(
        scan_id=scan.scan_id,
        launch_candidate_sha=scan.launch_candidates[0].sha,
        server_slug="trust_mcp",
        display_name="Trust MCP",
        config_values={},
        credential_bindings={"X_API_KEY": cred.credential_id},
        trust_to_probe=True,
        enable_for_session=False,
    ))

    assert result.probe.status == "ok"
    assert result.probe.tool_count == 1
    assert result.approval_state == "catalog_reviewed"


def test_install_with_trust_probe_and_enable_advances_all_the_way(
    installer: McpTemplateInstaller,
    scan_registry: McpScanRegistry,
    credential_store: RuntimeCredentialStore,
    tmp_path: Path,
):
    cred = credential_store.create(_make_credential_create())
    scan = _make_scan(source_path=tmp_path)
    scan_registry.register(scan)

    result = _await(installer.install(
        scan_id=scan.scan_id,
        launch_candidate_sha=scan.launch_candidates[0].sha,
        server_slug="enable_mcp",
        display_name="Enable MCP",
        config_values={},
        credential_bindings={"X_KEY": cred.credential_id},
        trust_to_probe=True,
        enable_for_session=True,
    ))

    assert result.approval_state == "enabled_for_session"


def test_install_probe_failure_stays_at_registered(
    installer: McpTemplateInstaller,
    scan_registry: McpScanRegistry,
    credential_store: RuntimeCredentialStore,
    mock_catalog: AsyncMock,
    tmp_path: Path,
):
    cred = credential_store.create(_make_credential_create())
    scan = _make_scan(source_path=tmp_path)
    scan_registry.register(scan)

    mock_catalog.get_tools.side_effect = McpServerLaunchError("simulated launch fail")

    result = _await(installer.install(
        scan_id=scan.scan_id,
        launch_candidate_sha=scan.launch_candidates[0].sha,
        server_slug="probe_fail",
        display_name="Probe Fail",
        config_values={},
        credential_bindings={"X_KEY": cred.credential_id},
        trust_to_probe=True,
    ))

    assert result.probe.status == "probe_failed"
    assert "McpServerLaunchError" in result.probe.reason
    assert result.approval_state == "registered"


def test_install_rejects_expired_scan(
    installer: McpTemplateInstaller,
    scan_registry: McpScanRegistry,
    tmp_path: Path,
):
    past = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat(timespec="seconds")
    scan = _make_scan(source_path=tmp_path).model_copy(update={"expires_at": past})
    scan_registry.register(scan)

    with pytest.raises(InstallScanExpiredError):
        _await(installer.install(
            scan_id=scan.scan_id,
            launch_candidate_sha=scan.launch_candidates[0].sha,
            server_slug="x", display_name="x",
            config_values={}, credential_bindings={},
            trust_to_probe=False,
        ))


def test_install_rejects_candidate_sha_mismatch(
    installer: McpTemplateInstaller,
    scan_registry: McpScanRegistry,
    tmp_path: Path,
):
    scan = _make_scan(source_path=tmp_path)
    scan_registry.register(scan)
    with pytest.raises(InstallCandidateMismatchError):
        _await(installer.install(
            scan_id=scan.scan_id,
            launch_candidate_sha="bogus_sha",
            server_slug="x", display_name="x",
            config_values={}, credential_bindings={},
            trust_to_probe=False,
        ))


def test_install_rejects_missing_credential(
    installer: McpTemplateInstaller,
    scan_registry: McpScanRegistry,
    tmp_path: Path,
):
    scan = _make_scan(source_path=tmp_path)
    scan_registry.register(scan)
    with pytest.raises(InstallCredentialMissingError):
        _await(installer.install(
            scan_id=scan.scan_id,
            launch_candidate_sha=scan.launch_candidates[0].sha,
            server_slug="x", display_name="x",
            config_values={},
            credential_bindings={"X_KEY": "cred_does_not_exist"},
            trust_to_probe=False,
        ))


def test_install_rejects_disabled_credential(
    installer: McpTemplateInstaller,
    scan_registry: McpScanRegistry,
    credential_store: RuntimeCredentialStore,
    tmp_path: Path,
):
    cred = credential_store.create(_make_credential_create())
    credential_store.update(cred.credential_id, RuntimeCredentialUpdate(enabled=False))
    scan = _make_scan(source_path=tmp_path)
    scan_registry.register(scan)

    with pytest.raises(InstallCredentialDisabledError):
        _await(installer.install(
            scan_id=scan.scan_id,
            launch_candidate_sha=scan.launch_candidates[0].sha,
            server_slug="x", display_name="x",
            config_values={},
            credential_bindings={"X_KEY": cred.credential_id},
            trust_to_probe=False,
        ))


def test_install_rejects_slug_conflict(
    installer: McpTemplateInstaller,
    scan_registry: McpScanRegistry,
    credential_store: RuntimeCredentialStore,
    tmp_path: Path,
):
    cred = credential_store.create(_make_credential_create())
    scan = _make_scan(source_path=tmp_path)
    scan_registry.register(scan)

    _await(installer.install(
        scan_id=scan.scan_id,
        launch_candidate_sha=scan.launch_candidates[0].sha,
        server_slug="dup_slug", display_name="A",
        config_values={}, credential_bindings={"K": cred.credential_id},
        trust_to_probe=False,
    ))

    scan2 = _make_scan(source_path=tmp_path)
    scan_registry.register(scan2)
    with pytest.raises(InstallSlugConflictError):
        _await(installer.install(
            scan_id=scan2.scan_id,
            launch_candidate_sha=scan2.launch_candidates[0].sha,
            server_slug="dup_slug", display_name="B",
            config_values={}, credential_bindings={"K": cred.credential_id},
            trust_to_probe=False,
        ))


# ===========================================================================
# Router (TestClient)
# ===========================================================================


def test_router_scan_registers_and_returns_result(
    client: TestClient,
    scan_registry: McpScanRegistry,
    tmp_path: Path,
):
    # Drop a manifest so the scanner finds something.
    manifest = {
        "schema_version": 1,
        "package_id": "lit-mcp-router-test",
        "display_name": "Router Test",
        "transport": "stdio",
        "launch": {"command": "python", "args": ["-m", "x"], "cwd": "."},
    }
    (tmp_path / "literature-mcp.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    r = client.post("/api/mcp/installations/scan", json={"source_path": str(tmp_path)})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["package_id"] == "lit-mcp-router-test"
    assert data["confidence"] == "high"
    assert len(data["launch_candidates"]) == 1
    assert scan_registry.size() == 1


def test_router_scan_rejects_remote_url(client: TestClient):
    r = client.post(
        "/api/mcp/installations/scan",
        json={"source_path": "https://evil.example.com/mcp.zip"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "scan_rejected"


def test_router_preview_returns_candidate(
    client: TestClient,
    scan_registry: McpScanRegistry,
    tmp_path: Path,
):
    scan = _make_scan(source_path=tmp_path)
    scan_registry.register(scan)

    r = client.post("/api/mcp/installations/preview", json={
        "scan_id": scan.scan_id,
        "launch_candidate_sha": scan.launch_candidates[0].sha,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scan_id"] == scan.scan_id
    assert body["candidate"]["sha"] == scan.launch_candidates[0].sha


def test_router_preview_404_unknown_scan(client: TestClient):
    r = client.post("/api/mcp/installations/preview", json={
        "scan_id": "scan_missing",
        "launch_candidate_sha": "abc",
    })
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "scan_not_found"


def test_router_preview_410_expired_scan(
    client: TestClient, scan_registry: McpScanRegistry, tmp_path: Path
):
    past = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat(timespec="seconds")
    scan = _make_scan(source_path=tmp_path).model_copy(update={"expires_at": past})
    scan_registry.register(scan)

    r = client.post("/api/mcp/installations/preview", json={
        "scan_id": scan.scan_id,
        "launch_candidate_sha": scan.launch_candidates[0].sha,
    })
    assert r.status_code == 410
    assert r.json()["detail"]["code"] == "scan_expired"


def test_router_install_happy_path_no_probe(
    client: TestClient,
    scan_registry: McpScanRegistry,
    credential_store: RuntimeCredentialStore,
    tmp_path: Path,
):
    cred = credential_store.create(_make_credential_create())
    scan = _make_scan(source_path=tmp_path)
    scan_registry.register(scan)

    r = client.post("/api/mcp/installations/install", json={
        "scan_id": scan.scan_id,
        "launch_candidate_sha": scan.launch_candidates[0].sha,
        "server_slug": "router_test_mcp",
        "display_name": "Router Test MCP",
        "config_values": {"DEBUG": "1"},
        "credential_bindings": {"SILICONFLOW_API_KEY": cred.credential_id},
        "trust_to_probe": False,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approval_state"] == "registered"
    assert body["probe"]["status"] == "skipped_untrusted"
    # Server config public never carries raw api_key.
    assert "api_key" not in json.dumps(body["server"])
    assert body["server"]["stdio"]["env_refs"] == {
        "SILICONFLOW_API_KEY": cred.credential_id
    }


def test_router_install_409_on_slug_conflict(
    client: TestClient,
    scan_registry: McpScanRegistry,
    credential_store: RuntimeCredentialStore,
    tmp_path: Path,
):
    cred = credential_store.create(_make_credential_create())
    scan_a = _make_scan(source_path=tmp_path)
    scan_registry.register(scan_a)
    r1 = client.post("/api/mcp/installations/install", json={
        "scan_id": scan_a.scan_id,
        "launch_candidate_sha": scan_a.launch_candidates[0].sha,
        "server_slug": "conflict_mcp",
        "display_name": "A",
        "config_values": {},
        "credential_bindings": {"K": cred.credential_id},
        "trust_to_probe": False,
    })
    assert r1.status_code == 200

    scan_b = _make_scan(source_path=tmp_path)
    scan_registry.register(scan_b)
    r2 = client.post("/api/mcp/installations/install", json={
        "scan_id": scan_b.scan_id,
        "launch_candidate_sha": scan_b.launch_candidates[0].sha,
        "server_slug": "conflict_mcp",
        "display_name": "B",
        "config_values": {},
        "credential_bindings": {"K": cred.credential_id},
        "trust_to_probe": False,
    })
    assert r2.status_code == 409
    assert r2.json()["detail"]["code"] == "server_slug_conflict"


def test_router_install_400_on_unknown_credential(
    client: TestClient,
    scan_registry: McpScanRegistry,
    tmp_path: Path,
):
    scan = _make_scan(source_path=tmp_path)
    scan_registry.register(scan)
    r = client.post("/api/mcp/installations/install", json={
        "scan_id": scan.scan_id,
        "launch_candidate_sha": scan.launch_candidates[0].sha,
        "server_slug": "x", "display_name": "x",
        "config_values": {}, "credential_bindings": {"K": "cred_nope"},
        "trust_to_probe": False,
    })
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "credential_not_found"


def test_router_install_400_on_disabled_credential(
    client: TestClient,
    scan_registry: McpScanRegistry,
    credential_store: RuntimeCredentialStore,
    tmp_path: Path,
):
    cred = credential_store.create(_make_credential_create())
    credential_store.update(cred.credential_id, RuntimeCredentialUpdate(enabled=False))
    scan = _make_scan(source_path=tmp_path)
    scan_registry.register(scan)

    r = client.post("/api/mcp/installations/install", json={
        "scan_id": scan.scan_id,
        "launch_candidate_sha": scan.launch_candidates[0].sha,
        "server_slug": "x", "display_name": "x",
        "config_values": {}, "credential_bindings": {"K": cred.credential_id},
        "trust_to_probe": False,
    })
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "credential_disabled"
