# -*- coding: utf-8 -*-
"""MemPalace integration layer for long-term project memory."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence
from uuid import uuid4

from datetime_utils import utc_now_iso_z

try:
    import yaml
except Exception:  # pragma: no cover - optional import guard
    yaml = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from harness_protocols import WritingArtifact, WritingEvent, WritingJob, WritingSession


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "rag_integration_config.yaml"
DEFAULT_VENDOR_REPO_PATH = PROJECT_ROOT / "github" / "mempalace-3.0.0"
DEFAULT_PALACE_PATH = PROJECT_ROOT / "output" / "mempalace" / "palace"
DEFAULT_COLLECTION_NAME = "mempalace_drawers"
DEFAULT_WING = "wing_modular_pipeline"
DEFAULT_ROOM = "runtime-jobs"
DEFAULT_SEARCH_LIMIT = 3
DEFAULT_MAX_CONTENT_CHARS = 4000


def _as_bool(value: Any, default: bool) -> bool:
    """Normalize a truthy configuration value."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _as_positive_int(value: Any, default: int) -> int:
    """Normalize a positive integer configuration value."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _resolve_path(value: Any, default: Path) -> Path:
    """Resolve a config path relative to the project root when needed."""
    if isinstance(value, str) and value.strip():
        candidate = Path(value.strip()).expanduser()
        return candidate if candidate.is_absolute() else (PROJECT_ROOT / candidate).resolve()
    return default.resolve()


def _iso_utc_now() -> str:
    """Return a UTC ISO-8601 timestamp."""
    return utc_now_iso_z()


@dataclass(frozen=True)
class MempalaceSettings:
    """Stable runtime settings for the MemPalace adapter."""

    enabled: bool
    vendor_repo_path: Path
    palace_path: Path
    collection_name: str
    default_wing: str
    default_room: str
    search_limit: int
    max_content_chars: int
    auto_sync_runtime_jobs: bool
    identity_path: Path | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize settings for diagnostics and API responses."""
        return {
            "enabled": self.enabled,
            "vendor_repo_path": str(self.vendor_repo_path),
            "palace_path": str(self.palace_path),
            "collection_name": self.collection_name,
            "default_wing": self.default_wing,
            "default_room": self.default_room,
            "search_limit": self.search_limit,
            "max_content_chars": self.max_content_chars,
            "auto_sync_runtime_jobs": self.auto_sync_runtime_jobs,
            "identity_path": str(self.identity_path) if self.identity_path else None,
        }


def load_mempalace_settings(config_path: str | Path = DEFAULT_CONFIG_PATH) -> MempalaceSettings:
    """Load MemPalace settings from config and environment overrides."""
    config_mapping: dict[str, Any] = {}
    resolved_config_path = Path(config_path).expanduser()
    if resolved_config_path.is_file() and yaml is not None:
        with open(resolved_config_path, "r", encoding="utf-8") as config_file:
            parsed = yaml.safe_load(config_file) or {}
        if isinstance(parsed, dict):
            config_mapping = parsed.get("mempalace", {}) if isinstance(parsed.get("mempalace", {}), dict) else {}

    enabled = _as_bool(os.environ.get("MEMPALACE_ENABLED", config_mapping.get("enabled")), False)
    vendor_repo_path = _resolve_path(
        os.environ.get("MEMPALACE_VENDOR_REPO", config_mapping.get("vendor_repo_path")),
        DEFAULT_VENDOR_REPO_PATH,
    )
    palace_path = _resolve_path(
        os.environ.get("MEMPALACE_PALACE_PATH", config_mapping.get("palace_path")),
        DEFAULT_PALACE_PATH,
    )
    collection_name = str(
        os.environ.get("MEMPALACE_COLLECTION_NAME", config_mapping.get("collection_name", DEFAULT_COLLECTION_NAME))
    ).strip() or DEFAULT_COLLECTION_NAME
    default_wing = str(
        os.environ.get("MEMPALACE_DEFAULT_WING", config_mapping.get("default_wing", DEFAULT_WING))
    ).strip() or DEFAULT_WING
    default_room = str(
        os.environ.get("MEMPALACE_DEFAULT_ROOM", config_mapping.get("default_room", DEFAULT_ROOM))
    ).strip() or DEFAULT_ROOM
    search_limit = _as_positive_int(
        os.environ.get("MEMPALACE_SEARCH_LIMIT", config_mapping.get("search_limit")),
        DEFAULT_SEARCH_LIMIT,
    )
    max_content_chars = _as_positive_int(
        os.environ.get("MEMPALACE_MAX_CONTENT_CHARS", config_mapping.get("max_content_chars")),
        DEFAULT_MAX_CONTENT_CHARS,
    )
    auto_sync_runtime_jobs = _as_bool(
        os.environ.get("MEMPALACE_AUTO_SYNC_RUNTIME", config_mapping.get("auto_sync_runtime_jobs")),
        enabled,
    )
    identity_override = os.environ.get("MEMPALACE_IDENTITY_PATH", config_mapping.get("identity_path"))
    identity_path = _resolve_path(
        identity_override,
        PROJECT_ROOT / "output" / "mempalace" / "identity.txt",
    )

    return MempalaceSettings(
        enabled=enabled,
        vendor_repo_path=vendor_repo_path,
        palace_path=palace_path,
        collection_name=collection_name,
        default_wing=default_wing,
        default_room=default_room,
        search_limit=search_limit,
        max_content_chars=max_content_chars,
        auto_sync_runtime_jobs=auto_sync_runtime_jobs,
        identity_path=identity_path,
    )


@dataclass(frozen=True)
class MemorySearchHit:
    """Normalized search hit returned from MemPalace."""

    text: str
    wing: str
    room: str
    source_file: str
    similarity: float

    @staticmethod
    def from_raw(raw: Mapping[str, Any]) -> "MemorySearchHit":
        """Build a typed hit from MemPalace search output."""
        similarity_value = raw.get("similarity", 0.0)
        try:
            similarity = float(similarity_value)
        except (TypeError, ValueError):
            similarity = 0.0
        return MemorySearchHit(
            text=str(raw.get("text", "")),
            wing=str(raw.get("wing", "unknown")),
            room=str(raw.get("room", "unknown")),
            source_file=str(raw.get("source_file", "")),
            similarity=similarity,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize hit to a JSON-safe payload."""
        return {
            "text": self.text,
            "wing": self.wing,
            "room": self.room,
            "source_file": self.source_file,
            "similarity": self.similarity,
        }


@dataclass(frozen=True)
class MemorySearchResponse:
    """Typed search response for API and workflow usage."""

    query: str
    wing: str | None
    room: str | None
    results: list[MemorySearchHit]
    available: bool
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize response to a JSON-safe payload."""
        return {
            "query": self.query,
            "wing": self.wing,
            "room": self.room,
            "available": self.available,
            "reason": self.reason,
            "results": [result.to_dict() for result in self.results],
        }


@dataclass(frozen=True)
class MemoryWakeupContext:
    """Typed wake-up context response."""

    wing: str | None
    context: str
    token_estimate: int
    available: bool
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize response to a JSON-safe payload."""
        return {
            "wing": self.wing,
            "context": self.context,
            "token_estimate": self.token_estimate,
            "available": self.available,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MemorySyncResult:
    """Result of filing a runtime event into MemPalace."""

    success: bool
    available: bool
    wing: str
    room: str
    drawer_id: str | None = None
    duplicate: bool = False
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize response to a JSON-safe payload."""
        return {
            "success": self.success,
            "available": self.available,
            "wing": self.wing,
            "room": self.room,
            "drawer_id": self.drawer_id,
            "duplicate": self.duplicate,
            "reason": self.reason,
        }


class MempalaceMemoryAdapter:
    """Defensive adapter around the vendored MemPalace package."""

    def __init__(self, settings: MempalaceSettings) -> None:
        if not isinstance(settings, MempalaceSettings):
            raise TypeError(f"settings must be MempalaceSettings, got {type(settings).__name__}")
        self.settings = settings

    def is_enabled(self) -> bool:
        """Return whether the integration is enabled by config."""
        return self.settings.enabled

    def describe(self) -> dict[str, Any]:
        """Return integration diagnostics without raising."""
        available, reason = self._diagnose_availability()
        payload = self.settings.to_public_dict()
        payload["available"] = available
        payload["reason"] = reason
        return payload

    def search(
        self,
        query: str,
        wing: str | None = None,
        room: str | None = None,
        limit: int | None = None,
    ) -> MemorySearchResponse:
        """Search MemPalace drawers with optional scope filters."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")

        resolved_wing = wing.strip() if isinstance(wing, str) and wing.strip() else self.settings.default_wing
        resolved_room = room.strip() if isinstance(room, str) and room.strip() else None
        if not self.settings.enabled:
            return MemorySearchResponse(
                query=query.strip(),
                wing=resolved_wing,
                room=resolved_room,
                results=[],
                available=False,
                reason="mempalace integration disabled by config",
            )

        try:
            searcher_module = self._import_module("mempalace.searcher")
            search_memories = getattr(searcher_module, "search_memories")
        except Exception as exc:  # pragma: no cover - import path diagnostics
            return MemorySearchResponse(
                query=query.strip(),
                wing=resolved_wing,
                room=resolved_room,
                results=[],
                available=False,
                reason=str(exc),
            )

        raw_result = search_memories(
            query=query.strip(),
            palace_path=str(self.settings.palace_path),
            wing=resolved_wing,
            room=resolved_room,
            n_results=limit or self.settings.search_limit,
        )
        if not isinstance(raw_result, dict):
            return MemorySearchResponse(
                query=query.strip(),
                wing=resolved_wing,
                room=resolved_room,
                results=[],
                available=False,
                reason="unexpected MemPalace search response",
            )

        if "error" in raw_result:
            return MemorySearchResponse(
                query=query.strip(),
                wing=resolved_wing,
                room=resolved_room,
                results=[],
                available=False,
                reason=str(raw_result["error"]),
            )

        raw_hits = raw_result.get("results", [])
        hits = [MemorySearchHit.from_raw(hit) for hit in raw_hits if isinstance(hit, Mapping)]
        return MemorySearchResponse(
            query=query.strip(),
            wing=resolved_wing,
            room=resolved_room,
            results=hits,
            available=True,
            reason=None,
        )

    def build_wakeup_context(self, wing: str | None = None) -> MemoryWakeupContext:
        """Render Layer0 + Layer1 context for a given project wing."""
        resolved_wing = wing.strip() if isinstance(wing, str) and wing.strip() else self.settings.default_wing
        if not self.settings.enabled:
            return MemoryWakeupContext(
                wing=resolved_wing,
                context="",
                token_estimate=0,
                available=False,
                reason="mempalace integration disabled by config",
            )

        try:
            layers_module = self._import_module("mempalace.layers")
            layer0_cls = getattr(layers_module, "Layer0")
            layer1_cls = getattr(layers_module, "Layer1")
        except Exception as exc:  # pragma: no cover - import path diagnostics
            return MemoryWakeupContext(
                wing=resolved_wing,
                context="",
                token_estimate=0,
                available=False,
                reason=str(exc),
            )

        identity_path = str(self.settings.identity_path) if self.settings.identity_path else None
        layer0 = layer0_cls(identity_path=identity_path)
        layer1 = layer1_cls(palace_path=str(self.settings.palace_path), wing=resolved_wing)
        context = f"{layer0.render().strip()}\n\n{layer1.generate().strip()}".strip()
        return MemoryWakeupContext(
            wing=resolved_wing,
            context=context,
            token_estimate=max(0, len(context) // 4),
            available=True,
            reason=None,
        )

    def add_memory(
        self,
        wing: str,
        room: str,
        content: str,
        *,
        source_file: str = "",
        metadata: Mapping[str, Any] | None = None,
        added_by: str = "modular-pipeline",
    ) -> MemorySyncResult:
        """Persist a normalized drawer into the MemPalace collection."""
        resolved_wing = wing.strip() if isinstance(wing, str) and wing.strip() else self.settings.default_wing
        resolved_room = room.strip() if isinstance(room, str) and room.strip() else self.settings.default_room
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content must be a non-empty string")
        if not self.settings.enabled:
            return MemorySyncResult(
                success=False,
                available=False,
                wing=resolved_wing,
                room=resolved_room,
                reason="mempalace integration disabled by config",
            )

        try:
            chromadb = self._import_chromadb()
        except Exception as exc:  # pragma: no cover - dependency diagnostics
            return MemorySyncResult(
                success=False,
                available=False,
                wing=resolved_wing,
                room=resolved_room,
                reason=str(exc),
            )

        normalized_content = content.strip()
        content_hash = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
        self.settings.palace_path.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(self.settings.palace_path))
        collection = client.get_or_create_collection(self.settings.collection_name)
        existing = collection.get(where={"content_hash": content_hash}, limit=1)
        if existing.get("ids"):
            existing_ids = existing.get("ids", [])
            return MemorySyncResult(
                success=True,
                available=True,
                wing=resolved_wing,
                room=resolved_room,
                drawer_id=str(existing_ids[0]) if existing_ids else None,
                duplicate=True,
                reason="content hash already filed",
            )

        drawer_id = f"drawer_{resolved_wing}_{resolved_room}_{uuid4().hex[:16]}"
        metadata_payload = {
            "wing": resolved_wing,
            "room": resolved_room,
            "source_file": str(source_file),
            "chunk_index": 0,
            "added_by": added_by,
            "filed_at": _iso_utc_now(),
            "content_hash": content_hash,
        }
        metadata_payload.update(self._normalize_metadata(metadata))
        collection.add(
            ids=[drawer_id],
            documents=[normalized_content],
            metadatas=[metadata_payload],
        )
        return MemorySyncResult(
            success=True,
            available=True,
            wing=resolved_wing,
            room=resolved_room,
            drawer_id=drawer_id,
            duplicate=False,
            reason=None,
        )

    def compose_runtime_memory_content(
        self,
        job: "WritingJob",
        session: "WritingSession | None",
        artifacts: Sequence["WritingArtifact"],
        events: Sequence["WritingEvent"],
    ) -> str:
        """Create a compact, loss-aware runtime summary for long-term memory."""
        if job is None:
            raise ValueError("job is required")

        sections: list[str] = [
            "## Runtime Job Memory",
            f"job_id: {job.job_id}",
            f"session_id: {job.session_id}",
            f"kind: {job.kind.value}",
            f"status: {job.status.value}",
            f"created_at: {job.created_at}",
        ]
        if job.started_at:
            sections.append(f"started_at: {job.started_at}")
        if job.completed_at:
            sections.append(f"completed_at: {job.completed_at}")
        if job.action_id:
            sections.append(f"action_id: {job.action_id}")
        if job.skill_id:
            sections.append(f"skill_id: {job.skill_id}")
        if job.scope:
            sections.append(f"scope: {job.scope}")
        if job.output_mode:
            sections.append(f"output_mode: {job.output_mode}")
        if job.tags:
            sections.append(f"tags: {', '.join(job.tags)}")
        if job.error:
            sections.append(f"error: {job.error}")

        if session is not None:
            sections.extend(
                [
                    "",
                    "## Session Context",
                    f"mode: {session.mode.value}",
                    f"user_id: {session.user_id or ''}",
                ]
            )
            if session.tags:
                sections.append(f"session_tags: {', '.join(session.tags)}")
            if session.settings:
                settings_json = json.dumps(session.settings, ensure_ascii=False, sort_keys=True)
                sections.append(f"session_settings: {settings_json}")

        if job.input_text.strip():
            sections.extend(["", "## Input", self._trim_text(job.input_text.strip(), 1000)])

        if artifacts:
            sections.append("")
            sections.append("## Artifacts")
            for artifact in artifacts[:5]:
                artifact_preview = self._serialize_content(artifact.content)
                sections.append(
                    f"[{artifact.artifact_type.value}] {self._trim_text(artifact_preview, 900)}"
                )

        if events:
            sections.append("")
            sections.append("## Event Trace")
            for event in events[-8:]:
                event_payload = json.dumps(event.data, ensure_ascii=False, sort_keys=True) if event.data else "{}"
                sections.append(
                    f"{event.timestamp} | {event.event_type.value} | {self._trim_text(event_payload, 400)}"
                )

        return self._trim_text("\n".join(sections).strip(), self.settings.max_content_chars)

    def sync_runtime_job(
        self,
        job: "WritingJob",
        session: "WritingSession | None",
        artifacts: Sequence["WritingArtifact"],
        events: Sequence["WritingEvent"],
        *,
        wing: str | None = None,
        room: str | None = None,
        source_file: str = "",
    ) -> MemorySyncResult:
        """Persist a terminal runtime job into MemPalace."""
        if job is None:
            raise ValueError("job is required")

        resolved_wing, resolved_room = self._resolve_sync_location(job, session, wing=wing, room=room)
        content = self.compose_runtime_memory_content(job, session, artifacts, events)
        metadata = {
            "job_id": job.job_id,
            "session_id": job.session_id,
            "job_kind": job.kind.value,
            "job_status": job.status.value,
            "artifact_count": len(artifacts),
            "event_count": len(events),
            "action_id": job.action_id,
            "skill_id": job.skill_id,
            "scope": job.scope,
            "output_mode": job.output_mode,
            "user_id": session.user_id if session else None,
        }
        return self.add_memory(
            resolved_wing,
            resolved_room,
            content,
            source_file=source_file or (job.action_id or job.skill_id or "writing-runtime"),
            metadata=metadata,
            added_by="modular-pipeline-runtime",
        )

    def _resolve_sync_location(
        self,
        job: "WritingJob",
        session: "WritingSession | None",
        *,
        wing: str | None,
        room: str | None,
    ) -> tuple[str, str]:
        """Resolve storage namespace using explicit overrides before session settings."""
        wing_candidates = [
            wing,
            session.settings.get("mempalace_wing") if session and isinstance(session.settings, dict) else None,
            session.metadata.get("mempalace_wing") if session and isinstance(session.metadata, dict) else None,
            self.settings.default_wing,
        ]
        room_candidates = [
            room,
            session.settings.get("mempalace_room") if session and isinstance(session.settings, dict) else None,
            session.metadata.get("mempalace_room") if session and isinstance(session.metadata, dict) else None,
            f"{self.settings.default_room}-{job.kind.value.replace('_', '-')}",
        ]

        resolved_wing = next(
            (candidate.strip() for candidate in wing_candidates if isinstance(candidate, str) and candidate.strip()),
            self.settings.default_wing,
        )
        resolved_room = next(
            (candidate.strip() for candidate in room_candidates if isinstance(candidate, str) and candidate.strip()),
            self.settings.default_room,
        )
        return resolved_wing, resolved_room

    def _diagnose_availability(self) -> tuple[bool, str | None]:
        """Best-effort runtime diagnosis for UI and API surfaces."""
        if not self.settings.enabled:
            return False, "mempalace integration disabled by config"
        if not self.settings.vendor_repo_path.exists() and importlib.util.find_spec("mempalace") is None:
            return False, f"mempalace package not found at {self.settings.vendor_repo_path}"
        try:
            self._import_chromadb()
        except Exception as exc:  # pragma: no cover - dependency diagnostics
            return False, str(exc)
        return True, None

    def _ensure_vendor_import_path(self) -> None:
        """Expose the vendored MemPalace package to Python when not installed."""
        if importlib.util.find_spec("mempalace") is not None:
            return
        if not self.settings.vendor_repo_path.is_dir():
            raise RuntimeError(f"mempalace package not found at {self.settings.vendor_repo_path}")
        vendor_repo = str(self.settings.vendor_repo_path)
        if vendor_repo not in sys.path:
            sys.path.insert(0, vendor_repo)

    def _import_module(self, module_name: str) -> Any:
        """Import a MemPalace submodule after ensuring the vendor path is visible."""
        self._ensure_vendor_import_path()
        return importlib.import_module(module_name)

    def _import_chromadb(self) -> Any:
        """Import chromadb lazily so tests do not require the dependency."""
        spec = importlib.util.find_spec("chromadb")
        if spec is None:
            raise RuntimeError("chromadb is not installed; install it to enable MemPalace storage")
        return importlib.import_module("chromadb")

    def _normalize_metadata(self, metadata: Mapping[str, Any] | None) -> dict[str, str | int | float | bool]:
        """Convert arbitrary metadata into Chroma-safe scalar fields."""
        if metadata is None:
            return {}
        normalized: dict[str, str | int | float | bool] = {}
        for key, value in metadata.items():
            if not isinstance(key, str) or not key.strip() or value is None:
                continue
            normalized_key = key.strip()
            if isinstance(value, (str, int, float, bool)):
                normalized[normalized_key] = value
                continue
            normalized[normalized_key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return normalized

    def _serialize_content(self, content: Any) -> str:
        """Serialize artifact content to text without losing the original shape."""
        if isinstance(content, str):
            return content
        if isinstance(content, Mapping):
            return json.dumps(content, ensure_ascii=False, sort_keys=True)
        if isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray)):
            return json.dumps(list(content), ensure_ascii=False)
        return str(content)

    def _trim_text(self, text: str, limit: int) -> str:
        """Trim long text defensively to the configured maximum size."""
        cleaned = text.strip()
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: max(0, limit - 3)].rstrip() + "..."
