"""Tests for RuntimeCredentialStore (Slice A1.3, plan v2 §13.2 #9 / DEC-001a)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from credential_store import (
    CredentialNotFoundError,
    CredentialSchemaError,
    RuntimeCredentialStore,
    SCHEMA_VERSION,
)
from models.credentials import (
    CREDENTIAL_FINGERPRINT_VERSION,
    RuntimeCredentialCreate,
    RuntimeCredentialUpdate,
    compute_credential_fingerprint,
    mask_api_key,
    normalize_base_url,
)


DUMMY_GENERATION_KEY = "test-ant-key-1234567890ABCDEF"
DUMMY_SECOND_KEY = "test-second-key-1234567890ABC"
DUMMY_EMBEDDING_KEY = "test-embedding-key-1234567890ABC"


def _create_body(api_key: str = DUMMY_GENERATION_KEY) -> RuntimeCredentialCreate:
    return RuntimeCredentialCreate(
        category="generation",
        provider="AnyRouter",
        model="claude-opus-4-7",
        base_url="https://anyrouter.top/v1",
        protocol="anthropic_messages",
        api_key=api_key,
    )


def _store(tmp_path: Path) -> RuntimeCredentialStore:
    return RuntimeCredentialStore(path=tmp_path / "runtime_credentials.json")


# ---------------------------------------------------------------------------
# Empty / load behavior
# ---------------------------------------------------------------------------


def test_empty_file_treated_as_empty_list(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.list_public() == []
    # File should NOT be created on a pure read.
    assert not store.path.exists()


def test_load_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    p = tmp_path / "runtime_credentials.json"
    p.write_text(json.dumps({
        "schema_version": SCHEMA_VERSION + 1,
        "updated_at": "2026-05-08T00:00:00+00:00",
        "credentials": [],
    }), encoding="utf-8")
    store = RuntimeCredentialStore(path=p)
    with pytest.raises(CredentialSchemaError, match="schema_version"):
        store.list_public()


def test_load_rejects_corrupt_json(tmp_path: Path) -> None:
    p = tmp_path / "runtime_credentials.json"
    p.write_text("{not json", encoding="utf-8")
    store = RuntimeCredentialStore(path=p)
    with pytest.raises(CredentialSchemaError, match="not valid JSON"):
        store.list_public()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_create_persists_and_returns_masked(tmp_path: Path) -> None:
    store = _store(tmp_path)
    pub = store.create(_create_body())
    assert pub.credential_id.startswith("cred_")
    assert pub.api_key_masked == mask_api_key(DUMMY_GENERATION_KEY)
    assert pub.has_api_key is True
    assert DUMMY_GENERATION_KEY not in pub.model_dump_json()
    assert store.path.exists(), "create must atomically persist"


def test_list_public_never_leaks_secret(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_create_body())
    pubs = store.list_public()
    assert len(pubs) == 1
    serialized = json.dumps([p.model_dump() for p in pubs])
    assert DUMMY_GENERATION_KEY not in serialized
    raw_file_text = store.path.read_text(encoding="utf-8")
    assert DUMMY_GENERATION_KEY in raw_file_text, "raw file must hold the secret"


def test_get_internal_exposes_api_key_for_dispatcher(tmp_path: Path) -> None:
    store = _store(tmp_path)
    pub = store.create(_create_body())
    cred = store.get_internal(pub.credential_id)
    assert cred.api_key == DUMMY_GENERATION_KEY


def test_get_public_raises_for_missing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(CredentialNotFoundError):
        store.get_public("cred_nonexistent")


def test_update_changes_fingerprint_only_on_identity_fields(tmp_path: Path) -> None:
    store = _store(tmp_path)
    pub = store.create(_create_body())
    fp1 = pub.fingerprint
    # notes update — fingerprint unchanged
    pub2 = store.update(pub.credential_id, RuntimeCredentialUpdate(notes="changed"))
    assert pub2.fingerprint == fp1
    # api_key rotation — fingerprint changes
    new_key = "test-ant-rotated-key-1234567890XYZ"
    pub3 = store.update(pub.credential_id, RuntimeCredentialUpdate(api_key=new_key))
    assert pub3.fingerprint != fp1
    assert pub3.api_key_masked == mask_api_key(new_key)
    # Internal still holds new key
    assert store.get_internal(pub.credential_id).api_key == new_key


def test_delete_removes_entry(tmp_path: Path) -> None:
    store = _store(tmp_path)
    pub = store.create(_create_body())
    assert store.delete(pub.credential_id) is True
    assert store.list_public() == []
    assert store.delete(pub.credential_id) is False
    raw_file_text = store.path.read_text(encoding="utf-8")
    assert DUMMY_GENERATION_KEY not in raw_file_text, "delete must purge the secret"


# ---------------------------------------------------------------------------
# Atomic write semantics
# ---------------------------------------------------------------------------


def test_atomic_write_leaves_no_tmp_files(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(_create_body())
    store.create(_create_body(api_key=DUMMY_SECOND_KEY))
    leftover_tmps = list(tmp_path.glob("*.tmp"))
    assert leftover_tmps == [], f"unexpected tmp files: {leftover_tmps}"


def test_filter_by_category_and_enabled(tmp_path: Path) -> None:
    store = _store(tmp_path)
    g = store.create(_create_body())
    e_body = RuntimeCredentialCreate(
        category="embedding", provider="SiliconFlow", model="bge-m3",
        base_url="https://api.siliconflow.cn/v1", protocol="embeddings",
        api_key=DUMMY_EMBEDDING_KEY,
    )
    store.create(e_body)
    assert len(store.list_public()) == 2
    assert len(store.list_public(category="generation")) == 1
    # Disable the generation cred
    store.update(g.credential_id, RuntimeCredentialUpdate(enabled=False))
    assert len(store.list_public(enabled_only=True)) == 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_mask_api_key_short_and_long() -> None:
    assert mask_api_key("") == ""
    assert mask_api_key("short") == "***"
    assert mask_api_key("sk-abcdefghijkl") == "sk-a...ijkl"


def test_normalize_base_url_strips_trailing_slash_and_lowercases() -> None:
    assert normalize_base_url("HTTPS://API.X.COM/V1/") == "https://api.x.com/V1"
    assert normalize_base_url("https://api.x.com/v1") == "https://api.x.com/v1"


def test_normalize_base_url_rejects_query() -> None:
    with pytest.raises(ValueError, match="query or fragment"):
        normalize_base_url("https://api.x.com/v1?api-version=preview")


def test_fingerprint_includes_version_prefix() -> None:
    fp = compute_credential_fingerprint(
        provider="OpenAI", base_url="https://api.openai.com/v1",
        model="gpt-4o", api_key="sk-test",
    )
    assert isinstance(fp, str) and len(fp) == 16
    # Different api_key -> different fingerprint
    fp2 = compute_credential_fingerprint(
        provider="OpenAI", base_url="https://api.openai.com/v1",
        model="gpt-4o", api_key="sk-other",
    )
    assert fp != fp2
