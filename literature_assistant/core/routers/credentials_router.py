# -*- coding: utf-8 -*-
"""Runtime Credentials API Router (Slice A3 / DEC-001b / DEC-002b).

Endpoints (plan v2 §5 Phase 3):
    GET    /api/credentials                       — list, masked
    POST   /api/credentials                       — create
    GET    /api/credentials/{credential_id}       — get one, masked
    PUT    /api/credentials/{credential_id}       — update (rotate or edit)
    DELETE /api/credentials/{credential_id}       — delete
    POST   /api/credentials/{credential_id}/test  — endpoint trust + reachability

Test endpoint contract (DEC-002b):
    1. Resolve credential by id (404 if missing)
    2. Run provider_endpoint_policy.validate_endpoint(...) BEFORE any
       Authorization header is constructed
    3. If decision.skipped_network → 200 with status="skipped"
    4. If not decision.allowed → 400 with masked decision dict
    5. If allowed → minimal HTTPS probe (HEAD with auth, no body, no redirects,
       short timeout). Response body NEVER echoed; only status_code + masked
       diagnostic.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from credential_store import (
    CredentialNotFoundError,
    CredentialSchemaError,
    RuntimeCredentialStore,
)
from models.credentials import (
    CredentialCategory,
    CredentialProtocol,
    CredentialStrategyHint,
    RuntimeCredentialCreate,
    RuntimeCredentialPublic,
    RuntimeCredentialUpdate,
    normalize_strategy_hint,
)
from provider_endpoint_policy import TrustSource, validate_endpoint

logger = logging.getLogger("CredentialsRouter")
router = APIRouter(prefix="/api/credentials", tags=["Credentials"])


# Module-level store singleton, reset-able for tests.
_store: RuntimeCredentialStore | None = None


def get_credential_store() -> RuntimeCredentialStore:
    global _store
    if _store is None:
        _store = RuntimeCredentialStore()
    return _store


def set_credential_store(store: RuntimeCredentialStore | None) -> None:
    """Test hook: inject a tmp-path-backed store, or reset to default."""
    global _store
    _store = store


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=list[RuntimeCredentialPublic])
async def list_credentials(
    category: str | None = None,
    enabled_only: bool = False,
    store: RuntimeCredentialStore = Depends(get_credential_store),
) -> list[RuntimeCredentialPublic]:
    """List credentials with masked api_key. Optionally filter by category /
    enabled.
    """
    try:
        return store.list_public(category=category, enabled_only=enabled_only)
    except CredentialSchemaError as exc:
        raise HTTPException(status_code=500, detail=f"credential store schema error: {exc}") from exc


@router.post("", response_model=RuntimeCredentialPublic)
async def create_credential(
    body: RuntimeCredentialCreate,
    store: RuntimeCredentialStore = Depends(get_credential_store),
) -> RuntimeCredentialPublic:
    """Create a new runtime credential. Body carries the secret on input only;
    response is masked.
    """
    return store.create(body)


@router.get("/{credential_id}", response_model=RuntimeCredentialPublic)
async def get_credential(
    credential_id: str,
    store: RuntimeCredentialStore = Depends(get_credential_store),
) -> RuntimeCredentialPublic:
    try:
        return store.get_public(credential_id)
    except CredentialNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"credential not found: {credential_id}") from exc


@router.put("/{credential_id}", response_model=RuntimeCredentialPublic)
async def update_credential(
    credential_id: str,
    body: RuntimeCredentialUpdate,
    store: RuntimeCredentialStore = Depends(get_credential_store),
) -> RuntimeCredentialPublic:
    try:
        return store.update(credential_id, body)
    except CredentialNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"credential not found: {credential_id}") from exc


@router.delete("/{credential_id}")
async def delete_credential(
    credential_id: str,
    store: RuntimeCredentialStore = Depends(get_credential_store),
) -> dict[str, Any]:
    deleted = store.delete(credential_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"credential not found: {credential_id}")
    return {"credential_id": credential_id, "deleted": True}


# ---------------------------------------------------------------------------
# Endpoint test (DEC-002b)
# ---------------------------------------------------------------------------


def _mask_decision(decision: Any) -> dict[str, Any]:
    """Return PolicyDecision.as_log_dict() — already secret-free by contract."""
    return decision.as_log_dict()


def _probe_https_endpoint(base_url: str, api_key: str, protocol: str) -> dict[str, Any]:
    """Send a minimal authenticated probe to verify reachability.

    Strategy:
      - HEAD request to base_url (no body, no redirects, short timeout)
      - If HEAD is not allowed (405/404), fall back to a tiny GET with no body
      - Authorization header constructed AFTER policy validation has passed
      - Response body / headers are NEVER echoed; only status_code + class

    Returns a mask-safe dict. Raises nothing (all exceptions caught).
    """
    import httpx  # local import keeps router import-cheap

    auth_header = _build_auth_header(api_key, protocol)
    headers = {**auth_header, "User-Agent": "literature-assistant-credential-test/1.0"}

    out: dict[str, Any] = {
        "probed": True,
        "url_used": base_url,
        "method": "HEAD",
    }
    try:
        with httpx.Client(timeout=5.0, follow_redirects=False) as client:
            resp = client.head(base_url, headers=headers)
            out["status_code"] = resp.status_code
            out["status_class"] = f"{resp.status_code // 100}xx"
            if resp.status_code in (404, 405):
                # Many providers reject HEAD; a tiny GET to the same path is acceptable.
                resp2 = client.get(base_url, headers=headers)
                out["method"] = "GET"
                out["status_code"] = resp2.status_code
                out["status_class"] = f"{resp2.status_code // 100}xx"
        out["ok"] = 200 <= out["status_code"] < 500  # 4xx (auth/route) still proves reachability
        out["reachable"] = True
        return out
    except httpx.TimeoutException:
        return {**out, "ok": False, "reachable": False, "error": "timeout"}
    except httpx.ConnectError:
        return {**out, "ok": False, "reachable": False, "error": "connect_error"}
    except httpx.HTTPError as exc:
        # Mask any URL/path detail beyond class name; never include raw exception text.
        return {**out, "ok": False, "reachable": False,
                "error": f"http_error:{type(exc).__name__}"}
    except Exception as exc:  # noqa: BLE001 — defense in depth for credential test
        logger.warning("credential test probe unexpected failure: %s", type(exc).__name__)
        return {**out, "ok": False, "reachable": False,
                "error": f"unexpected:{type(exc).__name__}"}


def _build_auth_header(api_key: str, protocol: str) -> dict[str, str]:
    """Map protocol -> auth header shape (DEC-002b).

    Per plan v2: header is constructed only after policy.allowed.
    """
    proto = (protocol or "").lower()
    if proto == CredentialProtocol.ANTHROPIC_MESSAGES.value:
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    if proto in {
        CredentialProtocol.OPENAI_CHAT_COMPLETIONS.value,
        CredentialProtocol.OPENAI_RESPONSES.value,
        CredentialProtocol.EMBEDDINGS.value,
        CredentialProtocol.RERANK.value,
    }:
        return {"Authorization": f"Bearer {api_key}"}
    # Unknown protocol: still use Bearer (most providers accept it).
    return {"Authorization": f"Bearer {api_key}"}


# ---------------------------------------------------------------------------
# Sampling (I5/D2: select credential by strategy_hint + category)
# ---------------------------------------------------------------------------


@router.post("/sample")
async def sample_credential(
    category: str | None = None,
    strategy_hint: str | None = None,
    store: RuntimeCredentialStore = Depends(get_credential_store),
) -> RuntimeCredentialPublic:
    """Sample a credential by category and strategy_hint.

    I5/D2 decision 2026-05-26: Discussion/SmartRead runtime credential selection.

    Query params:
        category: "generation" | "embedding" | "rerank" (optional, defaults to "generation")
        strategy_hint: cost/quality tier or surface hint (optional, defaults to "medium")

    Selection logic:
        1. Filter by category + enabled=True
        2. Normalize strategy_hint to canonical tier (cheap→low, default→medium, etc.)
        3. Match exact strategy_hint if possible
        4. Fall back to highest priority credential in category
        5. 404 if no enabled credentials in category

    Returns: RuntimeCredentialPublic (masked api_key)
    """

    # Normalize inputs
    target_category = CredentialCategory(category or "generation")
    normalized_hint = normalize_strategy_hint(strategy_hint)

    # Filter enabled credentials in category
    candidates = store.list_internal(category=target_category.value, enabled_only=True)
    if not candidates:
        raise HTTPException(
            status_code=404,
            detail=f"no enabled credentials found for category={target_category.value}",
        )

    # Try exact strategy_hint match first (normalize both sides for legacy compatibility)
    exact_matches = [
        c for c in candidates
        if normalize_strategy_hint(c.strategy_hint) == normalized_hint
    ]
    if exact_matches:
        # Sort by priority (lower number = higher priority), then by created_at (newer first)
        exact_matches.sort(key=lambda c: (c.priority, c.created_at), reverse=False)
        return exact_matches[0].to_public()

    # Fall back to highest priority credential in category
    candidates.sort(key=lambda c: (c.priority, c.created_at), reverse=False)
    return candidates[0].to_public()


@router.post("/{credential_id}/test")
async def test_credential(
    credential_id: str,
    body: dict[str, Any] | None = Body(default=None),
    store: RuntimeCredentialStore = Depends(get_credential_store),
) -> dict[str, Any]:
    """Validate endpoint trust and (if allowed) probe reachability.

    Per DEC-002b: the policy ALWAYS runs before any auth header is constructed.
    Per DEC-002c: untrusted_custom returns skipped_network=true unless caller
    overrides with body={"trust_source_override": "runtime_user_confirmed"}.
    The override is intentionally NOT persisted — it is a one-shot test mode.
    """
    try:
        cred = store.get_internal(credential_id)
    except CredentialNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"credential not found: {credential_id}"
        ) from exc

    # Optional one-shot trust upgrade for the test only (does NOT touch the store).
    trust_override = (body or {}).get("trust_source_override")
    effective_trust = trust_override or cred.trust_source.value
    if effective_trust not in {t.value for t in TrustSource}:
        raise HTTPException(
            status_code=400,
            detail=f"unknown trust_source_override: {trust_override}",
        )

    decision = validate_endpoint(cred.base_url, trust_source=effective_trust)
    decision_log = _mask_decision(decision)

    if decision.skipped_network:
        return {
            "credential_id": credential_id,
            "status": "skipped",
            "reason": decision.reason,
            "decision": decision_log,
            "probed": False,
        }

    if not decision.allowed:
        return {
            "credential_id": credential_id,
            "status": "rejected",
            "reason": decision.reason,
            "decision": decision_log,
            "probed": False,
        }

    # Authorization header is constructed only after policy.allowed.
    probe = _probe_https_endpoint(
        base_url=cred.base_url,
        api_key=cred.api_key,
        protocol=cred.protocol.value,
    )

    return {
        "credential_id": credential_id,
        "status": "ok" if probe.get("ok") else "probe_failed",
        "decision": decision_log,
        "probe": probe,
    }


__all__ = ["router", "get_credential_store", "set_credential_store"]
