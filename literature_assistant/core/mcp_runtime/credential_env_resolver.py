"""Resolve credential refs to raw env/headers at MCP spawn time.

Reads RuntimeCredentialStore via ``get_internal`` (the only path that returns
the raw api_key). Resolved values:

- NEVER appear in logs.
- NEVER appear in audit records (the audit layer logs the credential_id).
- NEVER appear in public API responses.
- Are merged into the subprocess env / HTTP headers in-process and then
  released by normal Python GC once the spawn / request completes.

Failure cases (all raised as ``CredentialRefError`` with a stable ``code``):

- ``credential_not_found``: ref points to a deleted / unknown credential.
- ``credential_disabled``: ref points to a credential with ``enabled=False``.

Caller (``mcp_runtime.client_manager``) bubbles these up as
``McpServerLaunchError`` so the probe / call surface stays unified.

Per plan 2026-05-20 §Locked Revisions M3 (single source of truth = env_refs
in MCP config) and §B3 (resolver runs immediately before process start).
"""

from __future__ import annotations

from typing import Mapping

from credential_store import CredentialNotFoundError, RuntimeCredentialStore


class CredentialRefError(RuntimeError):
    """Refers to a credential that does not exist or cannot be used.

    Attributes:
        code: Stable identifier for callers to switch on without parsing
              the message. One of ``credential_not_found`` /
              ``credential_disabled``.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class McpCredentialEnvResolver:
    """Resolve env_refs / header_refs against a RuntimeCredentialStore.

    The resolver is stateless aside from the store reference; one instance
    is safe to reuse across many spawns. Tests should inject a tmp-path
    store; production code uses the credentials_router singleton.
    """

    def __init__(self, credential_store: RuntimeCredentialStore | None = None) -> None:
        # Lazy default avoids forcing test code that doesn't touch resolver
        # to provision a credential store on import.
        self._store = (
            credential_store
            if credential_store is not None
            else RuntimeCredentialStore()
        )

    def resolve_env(
        self,
        explicit_env: Mapping[str, str],
        env_refs: Mapping[str, str],
    ) -> dict[str, str]:
        """Return the effective env dict for a stdio subprocess.

        Merge semantics: refs override explicit on key conflict. Rationale:
        explicit env is non-secret config (e.g. ``DEBUG=1``); refs carry
        secrets and must win if the operator mistakenly puts a placeholder
        of the same name in ``env``.
        """
        if not env_refs:
            return dict(explicit_env)
        merged: dict[str, str] = dict(explicit_env)
        for env_key, cred_id in env_refs.items():
            cred = self._fetch_enabled(cred_id, target=f"env ref {env_key!r}")
            merged[env_key] = cred.api_key
        return merged

    def resolve_headers(
        self,
        explicit_headers: Mapping[str, str],
        header_refs: Mapping[str, str],
    ) -> dict[str, str]:
        """Return the effective header dict for an HTTP request.

        Same merge semantics as ``resolve_env``: header_refs win on conflict.
        Header names preserve original casing as supplied by the caller —
        httpx normalizes case at request build time, so duplicate names
        differing only in case will collide there; we don't try to be smarter
        than httpx about HTTP header semantics.
        """
        if not header_refs:
            return dict(explicit_headers)
        merged: dict[str, str] = dict(explicit_headers)
        for header_name, cred_id in header_refs.items():
            cred = self._fetch_enabled(cred_id, target=f"header ref {header_name!r}")
            merged[header_name] = cred.api_key
        return merged

    # ------------------------------------------------------------------ helpers

    def _fetch_enabled(self, credential_id: str, *, target: str):
        try:
            cred = self._store.get_internal(credential_id)
        except CredentialNotFoundError as exc:
            raise CredentialRefError(
                "credential_not_found",
                f"{target} -> {credential_id!r}: credential not found",
            ) from exc
        if not cred.enabled:
            raise CredentialRefError(
                "credential_disabled",
                f"{target} -> {credential_id!r}: credential is disabled",
            )
        return cred


__all__ = [
    "CredentialRefError",
    "McpCredentialEnvResolver",
]
