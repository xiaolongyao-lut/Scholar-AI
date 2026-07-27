"""Resolve OCR credential references without persisting credential material."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Protocol

if TYPE_CHECKING:
    from literature_assistant.core.models.credentials import RuntimeCredential


_CREDENTIAL_ERROR_KEY = "_credential_error"
_PERSISTED_SECRET_KEYS = {
    "api_key",
    "authorization",
    "password",
    "secret",
    "token",
}


class OcrCredentialStore(Protocol):
    """Minimal credential-store contract required by OCR execution."""

    def get_internal(self, credential_id: str) -> "RuntimeCredential":
        """Return one internal credential without exposing it to API callers."""


def infer_remote_ocr_provider(provider_name: str, model_name: str) -> str:
    """Map saved credential metadata to one supported OCR adapter family."""

    text = f"{provider_name} {model_name}".strip().lower()
    if "mistral" in text:
        return "mistral"
    if "mineru" in text or "magic-pdf" in text:
        return "mineru"
    if "paddleocr" in text or "paddle ocr" in text:
        return "paddle_jobs"
    return "generic"


def remote_ocr_endpoint_path(provider: str, base_url: str) -> str:
    """Return a synchronous endpoint suffix, or empty for non-wired job APIs."""

    normalized = str(provider or "generic").strip().lower()
    url = str(base_url or "").strip().rstrip("/")
    if normalized == "mistral":
        return "" if url.endswith("/ocr") else "/ocr"
    if normalized == "mineru":
        return "" if url.endswith("/file-urls/batch") else "/v4/file-urls/batch"
    if normalized == "paddle_jobs":
        return ""
    return "/ocr"


def resolve_remote_ocr_credential_config(
    config: Mapping[str, Any] | None,
    *,
    credential_store: OcrCredentialStore | None = None,
) -> dict[str, Any]:
    """Resolve an OCR ``credential_id`` into an in-memory engine config.

    The saved credential owns its endpoint, provider family, model, and key.
    Caller-provided execution options such as upload consent and timeout remain
    intact, but cannot redirect a saved key to a different endpoint.
    """

    resolved = dict(config or {})
    resolved.pop(_CREDENTIAL_ERROR_KEY, None)
    raw_credential_id = resolved.get("credential_id")
    if raw_credential_id is None or raw_credential_id == "":
        return resolved

    for key in tuple(resolved):
        if str(key).lower() in _PERSISTED_SECRET_KEYS:
            resolved.pop(key, None)

    if not isinstance(raw_credential_id, str) or not raw_credential_id.strip():
        resolved[_CREDENTIAL_ERROR_KEY] = "saved OCR credential reference is invalid"
        return resolved
    credential_id = raw_credential_id.strip()
    resolved["credential_id"] = credential_id

    try:
        if TYPE_CHECKING:
            from literature_assistant.core.credential_store import (
                CredentialNotFoundError,
                CredentialSchemaError,
                CredentialSecretStorageError,
                RuntimeCredentialStore,
            )
        else:
            from credential_store import (
                CredentialNotFoundError,
                CredentialSchemaError,
                CredentialSecretStorageError,
                RuntimeCredentialStore,
            )

        store = credential_store if credential_store is not None else RuntimeCredentialStore()
        credential = store.get_internal(credential_id)
    except CredentialNotFoundError:
        resolved[_CREDENTIAL_ERROR_KEY] = "saved OCR credential was not found"
        return resolved
    except (CredentialSchemaError, CredentialSecretStorageError):
        resolved[_CREDENTIAL_ERROR_KEY] = "saved OCR credential could not be loaded"
        return resolved

    if not credential.enabled:
        resolved[_CREDENTIAL_ERROR_KEY] = "saved OCR credential is disabled"
        return resolved
    if credential.category.value != "ocr" or credential.protocol.value != "ocr":
        resolved[_CREDENTIAL_ERROR_KEY] = "saved credential is not configured for OCR"
        return resolved

    provider = infer_remote_ocr_provider(credential.provider, credential.model)
    endpoint_path = remote_ocr_endpoint_path(provider, credential.base_url)
    resolved.update(
        {
            "provider": provider,
            "base_url": credential.base_url,
            "model": credential.model,
            "api_key": credential.api_key,
        }
    )
    if endpoint_path:
        resolved["endpoint_path"] = endpoint_path
    else:
        resolved.pop("endpoint_path", None)
    return resolved


def prepare_ocr_engine_config_for_persistence(
    config: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Remove duplicated secrets when an opaque credential reference is saved."""

    persisted = dict(config or {})
    persisted.pop(_CREDENTIAL_ERROR_KEY, None)
    raw_credential_id = persisted.get("credential_id")
    if not isinstance(raw_credential_id, str) or not raw_credential_id.strip():
        return persisted
    persisted["credential_id"] = raw_credential_id.strip()
    for key in tuple(persisted):
        if str(key).lower() in _PERSISTED_SECRET_KEYS:
            persisted.pop(key, None)
    return persisted


__all__ = [
    "OcrCredentialStore",
    "infer_remote_ocr_provider",
    "prepare_ocr_engine_config_for_persistence",
    "remote_ocr_endpoint_path",
    "resolve_remote_ocr_credential_config",
]
