"""Tests for RuntimeMcpServerStore (Phase 1A / TASK-102).

Mirrors the credential_store test pattern (Slice A1) with MCP-specific
shape: stdio + streamable_http transports, approval state machine,
masked env/header dumps, namespace integrity (unique server_slug).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp.server_store import (
    McpApprovalTransitionError,
    McpServerNotFoundError,
    McpServerSchemaError,
    RuntimeMcpServerStore,
    SCHEMA_VERSION,
)
from models.mcp import (
    McpApprovalState,
    McpProvenance,
    McpServerConfigCreate,
    McpServerConfigUpdate,
    McpStdioConfig,
    McpStreamableHttpConfig,
    McpTransport,
    mask_env_value,
)


SECRET_ENV_VALUE = "test-serpapi-key-1234567890ABCDEF"  # pragma: allowlist secret
SECRET_HEADER = "Bearer test-bearer-1234567890ABCDEF"   # pragma: allowlist secret


def _stdio_create_body(
    *,
    slug: str = "echo-math",
    name: str = "Echo Math Fixture",
    env_value: str = SECRET_ENV_VALUE,
) -> McpServerConfigCreate:
    return McpServerConfigCreate(
        name=name,
        server_slug=slug,
        transport=McpTransport.STDIO,
        stdio=McpStdioConfig(
            command="python",
            args=["-m", "tests.fixtures.mcp.echo_math_server"],
            env={"FIXTURE_API_KEY": env_value},
        ),
        provenance=McpProvenance.RUNTIME_UNTRUSTED_CUSTOM,
    )


def _http_create_body(
    *,
    slug: str = "hosted-search",
    header: str = SECRET_HEADER,
) -> McpServerConfigCreate:
    return McpServerConfigCreate(
        name="Hosted Search",
        server_slug=slug,
        transport=McpTransport.STREAMABLE_HTTP,
        http=McpStreamableHttpConfig(
            url="https://mcp.example.com/sse",
            headers={"Authorization": header},
        ),
        provenance=McpProvenance.OFFICIAL_PROVIDER,
    )


def _store(tmp_path: Path) -> RuntimeMcpServerStore:
    return RuntimeMcpServerStore(path=tmp_path / "runtime_mcp_servers.json")


# ---------------------------------------------------------------------------
# Empty / load behavior
# ---------------------------------------------------------------------------


def test_empty_file_treated_as_empty_list(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.list_public() == []
    assert not store.path.exists()


def test_load_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    p = tmp_path / "runtime_mcp_servers.json"
    p.write_text(json.dumps({
        "schema_version": SCHEMA_VERSION + 1,
        "updated_at": "2026-05-09T00:00:00+00:00",
        "servers": [],
    }), encoding="utf-8")
    store = RuntimeMcpServerStore(path=p)
    with pytest.raises(McpServerSchemaError, match="schema_version"):
        store.list_public()


def test_load_rejects_corrupt_json(tmp_path: Path) -> None:
    p = tmp_path / "runtime_mcp_servers.json"
    p.write_text("{not json", encoding="utf-8")
    store = RuntimeMcpServerStore(path=p)
    with pytest.raises(McpServerSchemaError, match="not valid JSON"):
        store.list_public()


# ---------------------------------------------------------------------------
# CRUD: stdio
# ---------------------------------------------------------------------------


def test_create_stdio_persists_and_returns_masked(tmp_path: Path) -> None:
    store = _store(tmp_path)
    pub = store.create(_stdio_create_body())
    assert pub.server_id.startswith("mcp_")
    assert pub.server_slug == "echo-math"
    assert pub.transport == McpTransport.STDIO
    assert pub.approval_state == McpApprovalState.REGISTERED
    # Public dump masks env values
    assert pub.stdio is not None
    assert pub.stdio.env["FIXTURE_API_KEY"] == mask_env_value(SECRET_ENV_VALUE)
    assert SECRET_ENV_VALUE not in pub.model_dump_json()
    # Disk holds the raw secret
    raw = store.path.read_text(encoding="utf-8")
    assert SECRET_ENV_VALUE in raw


def test_create_http_persists_and_masks_headers(tmp_path: Path) -> None:
    store = _store(tmp_path)
    pub = store.create(_http_create_body())
    assert pub.transport == McpTransport.STREAMABLE_HTTP
    assert pub.http is not None
    assert pub.http.headers["Authorization"] == mask_env_value(SECRET_HEADER)
    assert SECRET_HEADER not in pub.model_dump_json()


def test_create_rejects_duplicate_server_slug(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_stdio_create_body(slug="dup"))
    with pytest.raises(ValueError, match="server_slug already in use"):
        store.create(_stdio_create_body(slug="dup", name="Other"))


def test_get_internal_exposes_raw_env_for_client_manager(tmp_path: Path) -> None:
    store = _store(tmp_path)
    pub = store.create(_stdio_create_body())
    internal = store.get_internal(pub.server_id)
    assert internal.stdio.env["FIXTURE_API_KEY"] == SECRET_ENV_VALUE


def test_get_public_raises_for_missing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(McpServerNotFoundError):
        store.get_public("mcp_nonexistent")


def test_list_public_filter_by_approval_state(tmp_path: Path) -> None:
    store = _store(tmp_path)
    a = store.create(_stdio_create_body(slug="a"))
    store.create(_stdio_create_body(slug="b"))
    # Promote a to catalog_reviewed
    store.update(a.server_id, McpServerConfigUpdate(
        approval_state=McpApprovalState.CATALOG_REVIEWED,
    ))
    registered = store.list_public(approval_state=McpApprovalState.REGISTERED)
    reviewed = store.list_public(approval_state=McpApprovalState.CATALOG_REVIEWED)
    assert len(registered) == 1 and registered[0].server_slug == "b"
    assert len(reviewed) == 1 and reviewed[0].server_slug == "a"


# ---------------------------------------------------------------------------
# Approval state machine
# ---------------------------------------------------------------------------


def test_approval_forward_step_allowed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    pub = store.create(_stdio_create_body())
    p1 = store.update(pub.server_id, McpServerConfigUpdate(
        approval_state=McpApprovalState.CATALOG_REVIEWED,
    ))
    assert p1.approval_state == McpApprovalState.CATALOG_REVIEWED
    p2 = store.update(pub.server_id, McpServerConfigUpdate(
        approval_state=McpApprovalState.ENABLED_FOR_SESSION,
    ))
    assert p2.approval_state == McpApprovalState.ENABLED_FOR_SESSION


def test_approval_skip_step_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    pub = store.create(_stdio_create_body())
    with pytest.raises(McpApprovalTransitionError):
        store.update(pub.server_id, McpServerConfigUpdate(
            approval_state=McpApprovalState.ENABLED_FOR_SESSION,
        ))


def test_approval_reset_to_registered_always_allowed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    pub = store.create(_stdio_create_body())
    store.update(pub.server_id, McpServerConfigUpdate(
        approval_state=McpApprovalState.CATALOG_REVIEWED,
    ))
    store.update(pub.server_id, McpServerConfigUpdate(
        approval_state=McpApprovalState.ENABLED_FOR_SESSION,
    ))
    # Reset all the way back
    p = store.update(pub.server_id, McpServerConfigUpdate(
        approval_state=McpApprovalState.REGISTERED,
    ))
    assert p.approval_state == McpApprovalState.REGISTERED


def test_approval_same_state_is_noop(tmp_path: Path) -> None:
    store = _store(tmp_path)
    pub = store.create(_stdio_create_body())
    p = store.update(pub.server_id, McpServerConfigUpdate(
        approval_state=McpApprovalState.REGISTERED,
    ))
    assert p.approval_state == McpApprovalState.REGISTERED


# ---------------------------------------------------------------------------
# Update / delete
# ---------------------------------------------------------------------------


def test_update_notes_only(tmp_path: Path) -> None:
    store = _store(tmp_path)
    pub = store.create(_stdio_create_body())
    p2 = store.update(pub.server_id, McpServerConfigUpdate(notes="checked 2026-05-09"))
    assert p2.notes == "checked 2026-05-09"
    assert p2.fingerprint == pub.fingerprint  # notes don't change identity


def test_update_missing_returns_404_style_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(McpServerNotFoundError):
        store.update("mcp_ghost", McpServerConfigUpdate(notes="x"))


def test_delete_removes_entry_and_purges_secret(tmp_path: Path) -> None:
    store = _store(tmp_path)
    pub = store.create(_stdio_create_body())
    assert store.delete(pub.server_id) is True
    assert store.list_public() == []
    assert store.delete(pub.server_id) is False
    raw = store.path.read_text(encoding="utf-8")
    assert SECRET_ENV_VALUE not in raw


# ---------------------------------------------------------------------------
# Atomic write semantics
# ---------------------------------------------------------------------------


def test_atomic_write_leaves_no_tmp_files(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_stdio_create_body(slug="a"))
    store.create(_stdio_create_body(slug="b", env_value="test-second-1234567890ABC"))  # pragma: allowlist secret
    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == [], f"unexpected tmp files: {leftover}"


# ---------------------------------------------------------------------------
# Model-level validation
# ---------------------------------------------------------------------------


def test_stdio_command_rejects_shell_metacharacters() -> None:
    with pytest.raises(ValueError, match="shell metacharacters"):
        McpStdioConfig(command="python; rm -rf /", args=[])


def test_invalid_slug_rejected() -> None:
    with pytest.raises(ValueError, match="server_slug"):
        McpServerConfigCreate(
            name="x",
            server_slug="UPPERCASE-NOT-OK",
            transport=McpTransport.STDIO,
            stdio=McpStdioConfig(command="python"),
        )


def test_transport_xor_block_required() -> None:
    with pytest.raises(ValueError, match="transport=stdio requires `stdio` block"):
        McpServerConfigCreate(
            name="x",
            server_slug="x",
            transport=McpTransport.STDIO,
            stdio=None,
        )
    with pytest.raises(ValueError, match="must not set `http` block"):
        McpServerConfigCreate(
            name="x",
            server_slug="x",
            transport=McpTransport.STDIO,
            stdio=McpStdioConfig(command="python"),
            http=McpStreamableHttpConfig(url="https://example.com"),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_mask_env_value_short_and_long() -> None:
    assert mask_env_value("") == ""
    assert mask_env_value("short") == "***"
    assert mask_env_value("test-abcdefghijkl") == "test...ijkl"


def test_fingerprint_includes_version_prefix() -> None:
    body1 = _stdio_create_body(slug="x")
    body2 = _stdio_create_body(slug="x", env_value="test-other-1234567890ABC")  # pragma: allowlist secret
    from models.mcp import _compute_server_fingerprint
    fp1 = _compute_server_fingerprint(body1)
    fp2 = _compute_server_fingerprint(body2)
    # Identity = name+slug+command+args+env_keys; env value rotation should
    # NOT change fingerprint.
    assert fp1 == fp2
    assert isinstance(fp1, str) and len(fp1) == 16
    # Slug change DOES change fingerprint.
    body3 = _stdio_create_body(slug="y")
    fp3 = _compute_server_fingerprint(body3)
    assert fp3 != fp1
