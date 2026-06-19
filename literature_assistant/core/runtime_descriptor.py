"""Runtime descriptor handoff for desktop-first MCP attachment."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from project_paths import (
    REPO_ROOT,
    WORKSPACE_RUNTIME_STATE_ROOT,
    api_port_file_path,
    desktop_runtime_closed_file_path,
    desktop_runtime_file_path,
)

DESKTOP_RUNTIME_SCHEMA_VERSION = 1
DEFAULT_DESKTOP_WINDOW_TITLE = "文献助手"


def utc_now_iso() -> str:
    """Return a UTC ISO timestamp accepted by JSON descriptors."""

    return datetime.now(timezone.utc).isoformat()


def build_desktop_runtime_descriptor(
    *,
    host: str,
    port: int,
    process_kind: str = "desktop",
    launched_by: str = "start_desktop.py",
    ready: bool = False,
    capability_file: str | Path | None = None,
    window_title: str = DEFAULT_DESKTOP_WINDOW_TITLE,
    started_at: str | None = None,
    active_project_id: str | None = None,
    active_runtime_session_id: str | None = None,
    active_chat_session_id: str | None = None,
    features: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Build the descriptor shared by desktop, backend, and MCP.

    Args:
        host: Loopback host where the local backend listens.
        port: TCP port for the local backend. Must be in the user-port range.
        process_kind: Runtime owner kind. First slice uses ``desktop``.
        launched_by: Human-readable launcher identity.
        ready: Whether backend health and capability handoff are ready.
        capability_file: Path to capability JSON. Token values are never stored.
        window_title: Native window title shown to the user.
        started_at: Stable process startup timestamp. Defaults to now.
        active_project_id: Optional UI hint populated by later slices.
        active_runtime_session_id: Optional runtime session hint.
        active_chat_session_id: Optional chat session hint.
        features: Feature availability flags for attach clients.

    Returns:
        JSON-serializable descriptor payload.
    """

    normalized_host = str(host or "").strip()
    if not normalized_host:
        raise ValueError("host must not be empty")
    if not isinstance(port, int) or port <= 0 or port > 65535:
        raise ValueError("port must be an integer between 1 and 65535")
    normalized_kind = str(process_kind or "").strip()
    if not normalized_kind:
        raise ValueError("process_kind must not be empty")
    normalized_launcher = str(launched_by or "").strip()
    if not normalized_launcher:
        raise ValueError("launched_by must not be empty")

    base_url = f"http://{normalized_host}:{port}"
    capability_path = str(Path(capability_file).expanduser().resolve()) if capability_file else None
    now = utc_now_iso()
    return {
        "schema_version": DESKTOP_RUNTIME_SCHEMA_VERSION,
        "runtime_id": f"{normalized_kind}_{os.getpid()}_{port}",
        "pid": os.getpid(),
        "process_kind": normalized_kind,
        "launched_by": normalized_launcher,
        "base_url": base_url,
        "frontend_url": f"{base_url}/",
        "host": normalized_host,
        "port": port,
        "window_title": window_title,
        "repo_root": str(REPO_ROOT),
        "runtime_state_root": str(WORKSPACE_RUNTIME_STATE_ROOT),
        "api_port_file": str(api_port_file_path()),
        "capability_file": capability_path,
        "started_at": started_at or now,
        "last_heartbeat_at": now,
        "ready": bool(ready),
        "active_project_id": active_project_id,
        "active_runtime_session_id": active_runtime_session_id,
        "active_chat_session_id": active_chat_session_id,
        "features": {
            "runtime_jobs": True,
            "agent_bridge": False,
            "wiki": True,
            "graph": True,
            "evolution": True,
            **(features or {}),
        },
    }


def write_desktop_runtime_descriptor(payload: dict[str, Any]) -> Path:
    """Atomically write the desktop runtime descriptor.

    Args:
        payload: JSON-serializable descriptor created by
            :func:`build_desktop_runtime_descriptor`.

    Returns:
        The descriptor path.
    """

    if not isinstance(payload, dict):
        raise TypeError("payload must be a dict")
    if payload.get("schema_version") != DESKTOP_RUNTIME_SCHEMA_VERSION:
        raise ValueError("unsupported desktop runtime descriptor schema")
    target = desktop_runtime_file_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(target.parent),
        prefix=target.name + ".",
        suffix=".tmp",
        delete=False,
    ) as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        tmp = Path(fh.name)
    os.replace(tmp, target)
    return target


def delete_desktop_runtime_closed_marker() -> None:
    """Clear the deliberate-close marker when a runtime starts again."""

    try:
        target = desktop_runtime_closed_file_path()
        if target.exists():
            target.unlink()
    except OSError:
        return


def refresh_desktop_runtime_descriptor(**updates: Any) -> Path | None:
    """Update the existing descriptor with a heartbeat and caller fields.

    Args:
        **updates: JSON-serializable fields to merge into the descriptor.

    Returns:
        The descriptor path when updated; ``None`` when no descriptor exists.
    """

    target = desktop_runtime_file_path()
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if int(payload.get("pid") or 0) != os.getpid():
        return None
    payload.update(updates)
    payload["schema_version"] = DESKTOP_RUNTIME_SCHEMA_VERSION
    payload["last_heartbeat_at"] = utc_now_iso()
    return write_desktop_runtime_descriptor(payload)


def write_desktop_runtime_closed_marker(reason: str = "window_closed") -> Path:
    """Atomically write a marker that suppresses MCP auto-relaunch.

    Args:
        reason: Short machine-readable close reason.

    Returns:
        The marker path.
    """

    normalized_reason = str(reason or "").strip()
    if not normalized_reason:
        raise ValueError("reason must not be empty")
    descriptor_payload: dict[str, Any] = {}
    descriptor_path = desktop_runtime_file_path()
    if descriptor_path.is_file():
        try:
            loaded = json.loads(descriptor_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            descriptor_payload = loaded
    payload = {
        "schema_version": DESKTOP_RUNTIME_SCHEMA_VERSION,
        "reason": normalized_reason,
        "closed_at": utc_now_iso(),
        "pid": os.getpid(),
        "repo_root": str(REPO_ROOT),
        "runtime_state_root": str(WORKSPACE_RUNTIME_STATE_ROOT),
        "last_runtime": {
            "base_url": descriptor_payload.get("base_url"),
            "frontend_url": descriptor_payload.get("frontend_url"),
            "port": descriptor_payload.get("port"),
            "window_title": descriptor_payload.get("window_title"),
            "started_at": descriptor_payload.get("started_at"),
        },
    }
    target = desktop_runtime_closed_file_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(target.parent),
        prefix=target.name + ".",
        suffix=".tmp",
        delete=False,
    ) as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        tmp = Path(fh.name)
    os.replace(tmp, target)
    return target


def delete_desktop_runtime_descriptor() -> None:
    """Remove the desktop runtime descriptor during clean shutdown."""

    try:
        target = desktop_runtime_file_path()
        if not target.exists():
            return
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict) and int(payload.get("pid") or 0) == os.getpid():
            target.unlink()
    except OSError:
        return
