"""Runtime MCP server registry (Phase 1A / TASK-102).

JSON-on-disk persistence under ``runtime_state_path("mcp_servers",
"runtime_mcp_servers.json")``. Atomic writes via the shared
``_atomic_io.atomic_write_json``, schema-version migration guard, masked
public dump, forward-only approval state machine.

Mirrors the credential_store pattern (Slice A1) but for MCP server config.
Public reads NEVER include raw env / header secret values.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from _atomic_io import atomic_write_json
from project_paths import runtime_state_path

from models.mcp import (
    McpApprovalState,
    McpServerConfig,
    McpServerConfigCreate,
    McpServerConfigPublic,
    McpServerConfigUpdate,
)


SCHEMA_VERSION = 1
DEFAULT_FILENAME = "runtime_mcp_servers.json"


def default_mcp_servers_path() -> Path:
    return runtime_state_path("mcp_servers", DEFAULT_FILENAME)


class McpServerNotFoundError(LookupError):
    pass


class McpServerSchemaError(ValueError):
    pass


class McpApprovalTransitionError(ValueError):
    """Raised when an update tries to skip or reverse the approval state machine."""


# Approval state machine: forward-only, monotonic.
_APPROVAL_ORDER = {
    McpApprovalState.REGISTERED: 0,
    McpApprovalState.CATALOG_REVIEWED: 1,
    McpApprovalState.ENABLED_FOR_SESSION: 2,
}


def _validate_approval_transition(
    current: McpApprovalState, target: McpApprovalState
) -> None:
    """Allow forward-only progression; downgrade requires explicit reset to
    REGISTERED. Same-state transitions are no-ops (allowed).
    """
    if target == current:
        return
    cur_rank = _APPROVAL_ORDER[current]
    tgt_rank = _APPROVAL_ORDER[target]
    if tgt_rank == cur_rank + 1:
        return  # standard forward step
    if target == McpApprovalState.REGISTERED:
        return  # explicit reset
    raise McpApprovalTransitionError(
        f"approval state cannot jump from {current.value} to {target.value}; "
        f"must step through the chain or reset to registered"
    )


class RuntimeMcpServerStore:
    """Persistent runtime MCP server registry.

    File layout (mirror SCHEMA_VERSION=1 of credential_store):
        {
            "schema_version": 1,
            "updated_at": "2026-05-09T...",
            "servers": [ <McpServerConfig serialized>, ... ]
        }

    Public API never exposes raw secrets in env / headers; callers receive
    ``McpServerConfigPublic`` (env / header values masked).
    Internal API (``get_internal`` / ``list_internal``) returns the full
    ``McpServerConfig`` for client_manager use only — never log the result.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path else default_mcp_servers_path()
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    # ------------------------------------------------------------------ load

    def _load_raw(self) -> dict:
        if not self._path.exists():
            return {
                "schema_version": SCHEMA_VERSION,
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "servers": [],
            }
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise McpServerSchemaError(
                f"runtime mcp servers file is not valid JSON: {self._path}"
            ) from exc
        if not isinstance(data, dict):
            raise McpServerSchemaError("runtime mcp servers root must be an object")
        version = data.get("schema_version")
        if not isinstance(version, int):
            raise McpServerSchemaError("missing or non-int schema_version")
        if version > SCHEMA_VERSION:
            raise McpServerSchemaError(
                f"runtime mcp servers schema_version={version} > supported "
                f"{SCHEMA_VERSION}; refusing to read"
            )
        servers = data.get("servers")
        if not isinstance(servers, list):
            raise McpServerSchemaError("servers must be a list")
        return data

    def _load_servers(self) -> list[McpServerConfig]:
        data = self._load_raw()
        out: list[McpServerConfig] = []
        for raw in data["servers"]:
            if not isinstance(raw, dict):
                raise McpServerSchemaError("each server must be an object")
            try:
                out.append(McpServerConfig.model_validate(raw))
            except Exception as exc:
                raise McpServerSchemaError(
                    f"server entry rejected by validator: {exc}"
                ) from exc
        return out

    # ----------------------------------------------------------------- write

    def _persist(self, servers: Iterable[McpServerConfig]) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "servers": [s.model_dump(mode="json") for s in servers],
        }
        atomic_write_json(self._path, payload)

    # ---------------------------------------------------------- public read

    def list_public(
        self,
        *,
        approval_state: McpApprovalState | None = None,
    ) -> list[McpServerConfigPublic]:
        with self._lock:
            servers = self._load_servers()
        out: list[McpServerConfigPublic] = []
        for s in servers:
            if approval_state and s.approval_state != approval_state:
                continue
            out.append(s.to_public())
        return out

    def get_public(self, server_id: str) -> McpServerConfigPublic:
        with self._lock:
            servers = self._load_servers()
        for s in servers:
            if s.server_id == server_id:
                return s.to_public()
        raise McpServerNotFoundError(server_id)

    # -------------------------------------------------------- internal read

    def list_internal(
        self,
        *,
        approval_state: McpApprovalState | None = None,
    ) -> list[McpServerConfig]:
        """Returns full server configs INCLUDING raw env/header secrets.
        Caller responsibility: never pass results into log / API response.
        Used by client_manager only.
        """
        with self._lock:
            servers = self._load_servers()
        if approval_state is None:
            return list(servers)
        return [s for s in servers if s.approval_state == approval_state]

    def get_internal(self, server_id: str) -> McpServerConfig:
        with self._lock:
            servers = self._load_servers()
        for s in servers:
            if s.server_id == server_id:
                return s
        raise McpServerNotFoundError(server_id)

    # ---------------------------------------------------------------- write

    def create(self, body: McpServerConfigCreate) -> McpServerConfigPublic:
        cred = McpServerConfig.from_create(body)
        with self._lock:
            existing = self._load_servers()
            # Reject duplicate server_slug — namespace integrity for
            # mcp__{slug}__{tool} naming.
            slug_taken = {s.server_slug for s in existing}
            if cred.server_slug in slug_taken:
                raise ValueError(f"server_slug already in use: {cred.server_slug!r}")
            existing.append(cred)
            self._persist(existing)
        return cred.to_public()

    def update(
        self, server_id: str, body: McpServerConfigUpdate
    ) -> McpServerConfigPublic:
        update = body.model_dump(exclude_unset=True, exclude_none=True)
        with self._lock:
            existing = self._load_servers()
            for i, s in enumerate(existing):
                if s.server_id == server_id:
                    if "approval_state" in update:
                        target = McpApprovalState(update["approval_state"])
                        _validate_approval_transition(s.approval_state, target)
                    merged = s.model_dump()
                    merged.update(update)
                    merged["updated_at"] = datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    )
                    updated = McpServerConfig.model_validate(merged)
                    existing[i] = updated
                    self._persist(existing)
                    return updated.to_public()
        raise McpServerNotFoundError(server_id)

    def delete(self, server_id: str) -> bool:
        with self._lock:
            existing = self._load_servers()
            for i, s in enumerate(existing):
                if s.server_id == server_id:
                    del existing[i]
                    self._persist(existing)
                    return True
        return False


__all__ = [
    "DEFAULT_FILENAME",
    "McpApprovalTransitionError",
    "McpServerNotFoundError",
    "McpServerSchemaError",
    "RuntimeMcpServerStore",
    "SCHEMA_VERSION",
    "default_mcp_servers_path",
]
