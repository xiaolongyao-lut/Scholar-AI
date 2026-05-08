"""Runtime credential store (Slice A1.2 / DEC-001a / plan v2 §13.2 #9).

JSON-on-disk persistence under runtime_state_path("credentials",
"runtime_credentials.json"). Atomic writes, schema-version migration guard,
masked public dump.

Thread-safe: all read/write operations acquire a module-level lock.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from _atomic_io import atomic_write_json
from project_paths import runtime_state_path

from models.credentials import (
    RuntimeCredential,
    RuntimeCredentialCreate,
    RuntimeCredentialPublic,
    RuntimeCredentialUpdate,
)


SCHEMA_VERSION = 1
DEFAULT_FILENAME = "runtime_credentials.json"


def default_credentials_path() -> Path:
    return runtime_state_path("credentials", DEFAULT_FILENAME)


class CredentialNotFoundError(LookupError):
    pass


class CredentialSchemaError(ValueError):
    pass


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Backwards-compat wrapper preserved for any external import (Slice A1
    public surface). New code should call ``_atomic_io.atomic_write_json``
    directly. This delegates to the shared implementation.
    """
    atomic_write_json(path, payload)


class RuntimeCredentialStore:
    """Persistent runtime credential registry.

    File layout (DEC-001a):
        {
            "schema_version": 1,
            "updated_at": "2026-05-08T...",
            "credentials": [ <RuntimeCredential serialized>, ... ]
        }

    Public API never returns api_key; callers receive RuntimeCredentialPublic.
    Internal API returns RuntimeCredential (for dispatcher use only).
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path else default_credentials_path()
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
                "credentials": [],
            }
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CredentialSchemaError(
                f"runtime credentials file is not valid JSON: {self._path}"
            ) from exc
        if not isinstance(data, dict):
            raise CredentialSchemaError("runtime credentials root must be an object")
        version = data.get("schema_version")
        if not isinstance(version, int):
            raise CredentialSchemaError("missing or non-int schema_version")
        if version > SCHEMA_VERSION:
            raise CredentialSchemaError(
                f"runtime credentials schema_version={version} > supported "
                f"{SCHEMA_VERSION}; refusing to read"
            )
        creds = data.get("credentials")
        if not isinstance(creds, list):
            raise CredentialSchemaError("credentials must be a list")
        return data

    def _load_credentials(self) -> list[RuntimeCredential]:
        data = self._load_raw()
        out: list[RuntimeCredential] = []
        for raw in data["credentials"]:
            if not isinstance(raw, dict):
                raise CredentialSchemaError("each credential must be an object")
            try:
                out.append(RuntimeCredential.model_validate(raw))
            except Exception as exc:
                raise CredentialSchemaError(
                    f"credential entry rejected by validator: {exc}"
                ) from exc
        return out

    # ----------------------------------------------------------------- write

    def _persist(self, credentials: Iterable[RuntimeCredential]) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "credentials": [c.model_dump(mode="json") for c in credentials],
        }
        _atomic_write_json(self._path, payload)

    # ---------------------------------------------------------- public read

    def list_public(
        self,
        *,
        category: str | None = None,
        enabled_only: bool = False,
    ) -> list[RuntimeCredentialPublic]:
        with self._lock:
            creds = self._load_credentials()
        out = []
        for c in creds:
            if category and c.category.value != category:
                continue
            if enabled_only and not c.enabled:
                continue
            out.append(c.to_public())
        return out

    def get_public(self, credential_id: str) -> RuntimeCredentialPublic:
        with self._lock:
            creds = self._load_credentials()
        for c in creds:
            if c.credential_id == credential_id:
                return c.to_public()
        raise CredentialNotFoundError(credential_id)

    # -------------------------------------------------------- internal read

    def list_internal(
        self,
        *,
        category: str | None = None,
        enabled_only: bool = True,
    ) -> list[RuntimeCredential]:
        """Internal API for dispatcher / pool merge. Includes api_key.

        Caller responsibility: never pass results into log / API response.
        """
        with self._lock:
            creds = self._load_credentials()
        out = []
        for c in creds:
            if category and c.category.value != category:
                continue
            if enabled_only and not c.enabled:
                continue
            out.append(c)
        return out

    def get_internal(self, credential_id: str) -> RuntimeCredential:
        with self._lock:
            creds = self._load_credentials()
        for c in creds:
            if c.credential_id == credential_id:
                return c
        raise CredentialNotFoundError(credential_id)

    # ---------------------------------------------------------------- write

    def create(self, body: RuntimeCredentialCreate) -> RuntimeCredentialPublic:
        cred = RuntimeCredential.from_create(body)
        with self._lock:
            existing = self._load_credentials()
            existing.append(cred)
            self._persist(existing)
        return cred.to_public()

    def update(
        self, credential_id: str, body: RuntimeCredentialUpdate
    ) -> RuntimeCredentialPublic:
        with self._lock:
            existing = self._load_credentials()
            for i, c in enumerate(existing):
                if c.credential_id == credential_id:
                    updated = c.with_update(body)
                    existing[i] = updated
                    self._persist(existing)
                    return updated.to_public()
        raise CredentialNotFoundError(credential_id)

    def delete(self, credential_id: str) -> bool:
        with self._lock:
            existing = self._load_credentials()
            for i, c in enumerate(existing):
                if c.credential_id == credential_id:
                    del existing[i]
                    self._persist(existing)
                    return True
        return False


__all__ = [
    "CredentialNotFoundError",
    "CredentialSchemaError",
    "DEFAULT_FILENAME",
    "RuntimeCredentialStore",
    "SCHEMA_VERSION",
    "default_credentials_path",
]
