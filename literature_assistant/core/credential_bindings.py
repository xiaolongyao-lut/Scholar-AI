"""Credential binding index.

In-memory reverse index of credential references made by MCP servers and
Skills. Source-of-truth lives in:

- the MCP stdio credential-reference map
- the MCP streamable HTTP header-reference map
- ``UserSkillManifest.required_credentials``

This module **does not persist** bindings. It rebuilds the reverse index by
scanning those stores at startup or on demand. Single source of truth = the
owner config; this index just answers "who uses this credential" cheaply
without scanning everything on every read.

Why no second store: avoids drift between owner configs and a parallel
binding table.

Thread-safe: rebuild / list operations acquire an internal RLock.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Iterable, Literal


OwnerKind = Literal["mcp_server", "skill"]


@dataclass(frozen=True, slots=True)
class CredentialBinding:
    """One reverse-index record: an owner references a credential under an env.

    Frozen so callers cannot mutate index state after retrieval. Never
    persisted independently — see module docstring.
    """

    owner_kind: OwnerKind
    owner_id: str
    target_env: str
    """Env var name (stdio) or header name (streamable_http) or skill env."""
    credential_id: str


class CredentialBindingIndex:
    """In-memory reverse index of credential usage across MCP and Skills.

    Lifecycle:
        1. App startup: call rebuild_from_mcp_store / rebuild_from_skill_registry.
        2. On MCP server create/update/delete: callers should call
           rebuild_from_mcp_store again. (Cheap; full rescan.)
        3. Reads (list_for, list_users_of) are O(n) over total bindings, which
           is fine for the expected scale (< 1k bindings per host).
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._bindings: list[CredentialBinding] = []

    # ----------------------------------------------------------------- writes

    def rebuild_from_mcp_store(self, mcp_configs: Iterable) -> None:
        """Replace all MCP-owned bindings by scanning the supplied configs.

        Skill bindings are preserved. The iterable yields the *internal*
        McpServerConfig (credential-reference maps accessible), never the
        public masked shape.
        """
        from models.mcp import McpTransport

        new_mcp: list[CredentialBinding] = []
        for cfg in mcp_configs:
            sid = cfg.server_id
            transport = cfg.transport
            if transport == McpTransport.STDIO and cfg.stdio is not None:
                env_refs = getattr(cfg.stdio, "env_refs", {}) or {}
                for env_key, cred_id in env_refs.items():
                    new_mcp.append(
                        CredentialBinding(
                            owner_kind="mcp_server",
                            owner_id=sid,
                            target_env=env_key,
                            credential_id=cred_id,
                        )
                    )
            elif transport == McpTransport.STREAMABLE_HTTP and cfg.http is not None:
                header_refs = getattr(cfg.http, "header_refs", {}) or {}
                for header_name, cred_id in header_refs.items():
                    new_mcp.append(
                        CredentialBinding(
                            owner_kind="mcp_server",
                            owner_id=sid,
                            target_env=header_name,
                            credential_id=cred_id,
                        )
                    )

        with self._lock:
            self._bindings = [
                b for b in self._bindings if b.owner_kind != "mcp_server"
            ]
            self._bindings.extend(new_mcp)

    def rebuild_from_skill_registry(
        self, skill_bindings: Iterable[CredentialBinding]
    ) -> None:
        """Replace all skill-owned bindings.

        Callers (skills_router / registry) materialize CredentialBinding
        entries from each skill's resolved required_credentials and pass them
        in. This keeps the index unaware of UserSkillManifest internals.
        """
        new_skill = [b for b in skill_bindings if b.owner_kind == "skill"]
        with self._lock:
            self._bindings = [b for b in self._bindings if b.owner_kind != "skill"]
            self._bindings.extend(new_skill)

    # ------------------------------------------------------------------ reads

    def list_for(
        self, owner_kind: OwnerKind, owner_id: str
    ) -> list[CredentialBinding]:
        """Return all bindings owned by the given (kind, id)."""
        with self._lock:
            return [
                b
                for b in self._bindings
                if b.owner_kind == owner_kind and b.owner_id == owner_id
            ]

    def list_users_of(self, credential_id: str) -> list[CredentialBinding]:
        """Return all owners that reference the given credential.

        Drives the credentials center "used by" column and lets the
        credentials router refuse deletion of in-use credentials.
        """
        with self._lock:
            return [b for b in self._bindings if b.credential_id == credential_id]

    def all(self) -> list[CredentialBinding]:
        """Snapshot of every binding. Used by audit / introspection."""
        with self._lock:
            return list(self._bindings)


# ---------------------------------------------------------------------------
# Module-level singleton (FastAPI / tests)
# ---------------------------------------------------------------------------


_singleton: CredentialBindingIndex | None = None


def get_credential_binding_index() -> CredentialBindingIndex:
    global _singleton
    if _singleton is None:
        _singleton = CredentialBindingIndex()
    return _singleton


def set_credential_binding_index(index: CredentialBindingIndex | None) -> None:
    """Test hook: inject a fresh index or reset to default."""
    global _singleton
    _singleton = index


__all__ = [
    "CredentialBinding",
    "CredentialBindingIndex",
    "OwnerKind",
    "get_credential_binding_index",
    "set_credential_binding_index",
]
