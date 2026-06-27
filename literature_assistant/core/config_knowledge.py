"""Read-only knowledge projection for Scholar AI runtime JSON config."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from json import JSONDecodeError
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path used by the running app.
    from literature_assistant.core.project_paths import REPO_ROOT
except ImportError:  # pragma: no cover - flat import path used by legacy tests.
    from project_paths import REPO_ROOT


SCORING_RULES_KNOWLEDGE_SCHEMA_VERSION = "scholar-ai-scoring-rules-knowledge/v1"
SCORING_RULES_REF_SCHEMA_VERSION = "scholar-ai-scoring-rules-knowledge-ref/v1"
SCORING_RULES_PACKAGE_ID = "config:scoring_rules"
SCORING_RULES_CONFIG_ID = "scoring_rules"
MAX_SCORING_RULES_BYTES = 512 * 1024
MAX_SCORING_RULES_SEARCH_RESULTS = 50
SCORING_RULES_SECTIONS = ("weights", "thresholds", "multipliers", "goal_mapping")


@dataclass(frozen=True)
class ConfigSource:
    """One authoritative JSON config source used by the projection."""

    relative_path: str
    loaded: bool
    content_hash: str
    char_count: int
    byte_count: int
    updated_at: str
    warning: str | None = None


@dataclass(frozen=True)
class ConfigSectionChunk:
    """One bounded config section ref derived from scoring_rules.json."""

    section_id: str
    title: str
    source_path: str
    source_hash: str
    content_hash: str
    span_start: int
    span_end: int
    text: str

    @property
    def ref_id(self) -> str:
        """Return the agent-readable resource ref for this config section."""

        return build_scoring_rules_ref_id(self.section_id)

    @property
    def read_endpoint(self) -> str:
        """Return the bounded resource endpoint for this config section."""

        return f"/api/agent-bridge/resource/{self.ref_id}"


@dataclass(frozen=True)
class ScoringRulesSnapshot:
    """Read-only source/ref/provenance status for scoring_rules.json."""

    package_id: str
    config_id: str
    source_path: str
    source_hash: str
    content_hash: str
    loaded: bool
    manifest_loaded: bool
    load_status: str
    updated_at: str
    title: str
    description: str
    version: str
    last_updated: str
    source: ConfigSource
    sections: list[ConfigSectionChunk] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    runtime_consumers: list[dict[str, str]] = field(default_factory=list)

    def to_status_payload(self, *, include_sections: bool = False) -> dict[str, Any]:
        """Return a JSON-safe status payload without embedding full text by default."""

        payload: dict[str, Any] = {
            "schema_version": SCORING_RULES_KNOWLEDGE_SCHEMA_VERSION,
            "package_id": self.package_id,
            "config_id": self.config_id,
            "source_path": self.source_path,
            "source_hash": self.source_hash,
            "content_hash": self.content_hash,
            "loaded": self.loaded,
            "manifest_loaded": self.manifest_loaded,
            "load_status": self.load_status,
            "updated_at": self.updated_at,
            "title": self.title,
            "description": self.description,
            "version": self.version,
            "last_updated": self.last_updated,
            "source": asdict(self.source),
            "section_count": len(self.sections),
            "warnings": list(self.warnings),
            "manifest": dict(self.manifest),
            "runtime_consumers": [dict(item) for item in self.runtime_consumers],
        }
        if include_sections:
            payload["sections"] = [
                {
                    "section_id": section.section_id,
                    "ref_id": section.ref_id,
                    "read_endpoint": section.read_endpoint,
                    "title": section.title,
                    "source_path": section.source_path,
                    "source_hash": section.source_hash,
                    "content_hash": section.content_hash,
                    "span_start": section.span_start,
                    "span_end": section.span_end,
                    "char_count": len(section.text),
                }
                for section in self.sections
            ]
        return payload


def scoring_rules_config_path() -> Path:
    """Return the authoritative repo-local scoring rules JSON path."""

    return REPO_ROOT / "literature_assistant" / "core" / "config" / "scoring_rules.json"


def build_scoring_rules_ref_id(section_id: str) -> str:
    """Return a stable agent resource ref for one scoring-rules section."""

    normalized = _normalize_section_id(section_id)
    return f"scoring_rules:section:{normalized}"


def load_scoring_rules_snapshot(source_path: Path | None = None) -> ScoringRulesSnapshot:
    """Load scoring_rules.json as a read-only runtime knowledge snapshot."""

    path = source_path or scoring_rules_config_path()
    source_path_ref = _repo_relative(path)
    warnings: list[str] = []
    missing_source = ConfigSource(
        relative_path=source_path_ref,
        loaded=False,
        content_hash="unknown",
        char_count=0,
        byte_count=0,
        updated_at="unknown",
        warning="missing",
    )
    if not path.exists():
        warnings.append("scoring_rules.json is missing.")
        return _snapshot(
            source_path_ref=source_path_ref,
            source_hash="unknown",
            content_hash="unknown",
            loaded=False,
            manifest_loaded=False,
            load_status="missing",
            updated_at="unknown",
            source=missing_source,
            warnings=warnings,
        )

    try:
        if path.stat().st_size > MAX_SCORING_RULES_BYTES:
            raise OSError(f"file exceeds {MAX_SCORING_RULES_BYTES} bytes")
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        warnings.append(f"Could not read scoring_rules.json: {exc}")
        return _snapshot(
            source_path_ref=source_path_ref,
            source_hash="unknown",
            content_hash="unknown",
            loaded=False,
            manifest_loaded=False,
            load_status="missing",
            updated_at=_path_updated_at(path),
            source=ConfigSource(
                relative_path=source_path_ref,
                loaded=False,
                content_hash="unknown",
                char_count=0,
                byte_count=0,
                updated_at=_path_updated_at(path),
                warning=str(exc),
            ),
            warnings=warnings,
        )

    source_hash = _sha256_text(raw_text)
    source = ConfigSource(
        relative_path=source_path_ref,
        loaded=True,
        content_hash=source_hash,
        char_count=len(raw_text),
        byte_count=len(raw_text.encode("utf-8")),
        updated_at=_path_updated_at(path),
    )
    try:
        data = json.loads(raw_text)
    except JSONDecodeError as exc:
        warnings.append(f"scoring_rules.json is invalid JSON: {exc.msg}")
        return _snapshot(
            source_path_ref=source_path_ref,
            source_hash=source_hash,
            content_hash=source_hash,
            loaded=False,
            manifest_loaded=False,
            load_status="invalid",
            updated_at=_path_updated_at(path),
            source=source,
            warnings=warnings,
        )
    if not isinstance(data, dict):
        warnings.append("scoring_rules.json must contain a JSON object.")
        return _snapshot(
            source_path_ref=source_path_ref,
            source_hash=source_hash,
            content_hash=source_hash,
            loaded=False,
            manifest_loaded=False,
            load_status="invalid",
            updated_at=_path_updated_at(path),
            source=source,
            warnings=warnings,
        )

    sections = _build_sections(data, source_path_ref, source_hash, raw_text, warnings)
    loaded = bool(sections) and all(section in data for section in SCORING_RULES_SECTIONS)
    if not loaded:
        warnings.append("scoring_rules.json is missing one or more required sections.")
    canonical_json = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _snapshot(
        source_path_ref=source_path_ref,
        source_hash=source_hash,
        content_hash=_sha256_text(canonical_json),
        loaded=loaded,
        manifest_loaded=loaded,
        load_status="loaded" if loaded else "invalid",
        updated_at=_path_updated_at(path),
        source=source,
        sections=sections,
        manifest=_manifest(data),
        warnings=warnings,
    )


def get_scoring_rules_status() -> dict[str, Any]:
    """Return source/ref/provenance status for scoring_rules.json."""

    return load_scoring_rules_snapshot().to_status_payload(include_sections=True)


def read_scoring_rules() -> dict[str, Any]:
    """Return scoring_rules.json data with status metadata for bounded callers."""

    snapshot = load_scoring_rules_snapshot()
    entries: dict[str, Any] = {}
    for section in snapshot.sections:
        try:
            entries[section.section_id] = json.loads(section.text)
        except JSONDecodeError:
            entries[section.section_id] = section.text
    return {
        **snapshot.to_status_payload(include_sections=True),
        "entries": entries,
    }


def search_scoring_rules(query: str, *, top_k: int = 8) -> list[dict[str, Any]]:
    """Search scoring-rules sections and return bounded resource refs."""

    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise ValueError("query must not be empty")
    if top_k < 1 or top_k > MAX_SCORING_RULES_SEARCH_RESULTS:
        raise ValueError(f"top_k must be between 1 and {MAX_SCORING_RULES_SEARCH_RESULTS}")

    snapshot = load_scoring_rules_snapshot()
    terms = _query_terms(normalized_query)
    hits: list[tuple[int, ConfigSectionChunk]] = []
    for section in snapshot.sections:
        score = _score_section(section, terms, normalized_query)
        if score > 0:
            hits.append((score, section))
    hits.sort(key=lambda item: (-item[0], item[1].section_id))

    return [
        {
            "schema_version": SCORING_RULES_REF_SCHEMA_VERSION,
            "ref_id": section.ref_id,
            "kind": "scoring_rules",
            "resource_kind": "section",
            "title": section.title,
            "summary": _summary_for_query(section.text, terms),
            "score": float(score),
            "rank": index,
            "read_endpoint": section.read_endpoint,
            "metadata": _section_metadata(section, snapshot),
        }
        for index, (score, section) in enumerate(hits[:top_k], start=1)
    ]


def read_scoring_rules_resource(raw_ref: str) -> dict[str, Any]:
    """Resolve one `scoring_rules:section:<section_id>` resource ref."""

    section_id = _parse_scoring_rules_raw_ref(raw_ref)
    snapshot = load_scoring_rules_snapshot()
    for section in snapshot.sections:
        if section.section_id == section_id:
            return {
                "kind": "scoring_rules",
                "project_id": None,
                "title": section.title,
                "content": section.text,
                "metadata": _section_metadata(section, snapshot),
                "ref_id": section.ref_id,
            }
    raise KeyError(f"Scoring rules section not found: {section_id}")


def _snapshot(
    *,
    source_path_ref: str,
    source_hash: str,
    content_hash: str,
    loaded: bool,
    manifest_loaded: bool,
    load_status: str,
    updated_at: str,
    source: ConfigSource,
    sections: list[ConfigSectionChunk] | None = None,
    manifest: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> ScoringRulesSnapshot:
    return ScoringRulesSnapshot(
        package_id=SCORING_RULES_PACKAGE_ID,
        config_id=SCORING_RULES_CONFIG_ID,
        source_path=source_path_ref,
        source_hash=source_hash,
        content_hash=content_hash,
        loaded=loaded,
        manifest_loaded=manifest_loaded,
        load_status=load_status,
        updated_at=updated_at,
        title="Scoring Rules",
        description=str((manifest or {}).get("description") or "Academic paper evidence quality scoring configuration"),
        version=str((manifest or {}).get("version") or "unknown"),
        last_updated=str((manifest or {}).get("last_updated") or "unknown"),
        source=source,
        sections=list(sections or []),
        manifest=dict(manifest or {}),
        warnings=list(warnings or []),
        runtime_consumers=_runtime_consumers(),
    )


def _build_sections(
    data: dict[str, Any],
    source_path_ref: str,
    source_hash: str,
    raw_text: str,
    warnings: list[str],
) -> list[ConfigSectionChunk]:
    sections: list[ConfigSectionChunk] = []
    for section_id in SCORING_RULES_SECTIONS:
        section_value = data.get(section_id)
        if not isinstance(section_value, dict):
            warnings.append(f"scoring_rules.{section_id} must be an object.")
            continue
        text = json.dumps(section_value, ensure_ascii=False, sort_keys=True, indent=2)
        span_start, span_end = _best_effort_section_span(raw_text, section_id)
        sections.append(
            ConfigSectionChunk(
                section_id=section_id,
                title=f"Scoring Rules: {section_id}",
                source_path=source_path_ref,
                source_hash=source_hash,
                content_hash=_sha256_text(text),
                span_start=span_start,
                span_end=span_end,
                text=text,
            )
        )
    return sections


def _manifest(data: dict[str, Any]) -> dict[str, Any]:
    sections = {
        section_id: len(value)
        for section_id, value in data.items()
        if section_id in SCORING_RULES_SECTIONS and isinstance(value, dict)
    }
    return {
        "version": str(data.get("version") or "unknown"),
        "last_updated": str(data.get("last_updated") or "unknown"),
        "description": str(data.get("description") or ""),
        "required_sections": list(SCORING_RULES_SECTIONS),
        "sections": sections,
        "runtime_mutability": "read_only",
    }


def _section_metadata(section: ConfigSectionChunk, snapshot: ScoringRulesSnapshot) -> dict[str, Any]:
    return {
        "knowledge_ref_schema_version": SCORING_RULES_REF_SCHEMA_VERSION,
        "ref_id": section.ref_id,
        "package_id": snapshot.package_id,
        "config_id": snapshot.config_id,
        "resource_kind": "section",
        "section_id": section.section_id,
        "source": "scoring_rules",
        "source_type": "json_config",
        "source_path": section.source_path,
        "source_hash": section.source_hash,
        "content_hash": section.content_hash,
        "package_content_hash": snapshot.content_hash,
        "span_start": section.span_start,
        "span_end": section.span_end,
        "read_endpoint": section.read_endpoint,
        "runtime_consumers": [dict(item) for item in snapshot.runtime_consumers],
    }


def _parse_scoring_rules_raw_ref(raw_ref: str) -> str:
    normalized = str(raw_ref or "").strip()
    parts = normalized.split(":")
    if len(parts) != 2 or parts[0] != "section":
        raise ValueError("scoring_rules refs must use section:<section_id>")
    return _normalize_section_id(parts[1])


def _normalize_section_id(section_id: str) -> str:
    normalized = str(section_id or "").strip()
    if normalized not in SCORING_RULES_SECTIONS:
        raise ValueError(f"Unsupported scoring rules section: {section_id}")
    return normalized


def _query_terms(query: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", query.lower())
    return [term for term in terms if term]


def _score_section(section: ConfigSectionChunk, terms: list[str], query: str) -> int:
    text = section.text.lower()
    title = section.title.lower()
    score = 0
    for term in terms:
        score += text.count(term)
        if term in title:
            score += 3
    if query.lower() in text:
        score += 5
    return score


def _summary_for_query(text: str, terms: list[str], *, max_chars: int = 420) -> str:
    clean_text = " ".join(str(text or "").split())
    if len(clean_text) <= max_chars:
        return clean_text
    lower_text = clean_text.lower()
    first_hit = min((lower_text.find(term) for term in terms if lower_text.find(term) >= 0), default=0)
    start = max(0, first_hit - 80)
    end = min(len(clean_text), start + max_chars)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(clean_text) else ""
    return f"{prefix}{clean_text[start:end].strip()}{suffix}"


def _best_effort_section_span(raw_text: str, section_id: str) -> tuple[int, int]:
    needle = f'"{section_id}"'
    start = raw_text.find(needle)
    if start < 0:
        return 0, len(raw_text)
    next_starts = [
        raw_text.find(f'"{candidate}"', start + len(needle))
        for candidate in SCORING_RULES_SECTIONS
        if candidate != section_id
    ]
    next_positive = [position for position in next_starts if position > start]
    end = min(next_positive) if next_positive else len(raw_text)
    return start, end


def _path_updated_at(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
    except OSError:
        return "unknown"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.name
    except OSError:
        return path.as_posix()


def _runtime_consumers() -> list[dict[str, str]]:
    return [
        {
            "consumer": "literature_assistant.core.modules.configuration_manager",
            "use": "runtime scoring configuration source",
        },
        {
            "consumer": "literature_assistant.core.routers.knowledge_router",
            "use": "read-only package registry and scoring-rules search",
        },
        {
            "consumer": "literature_assistant.core.routers.agent_bridge_router",
            "use": "bounded resource loading through agent_resource_read",
        },
        {
            "consumer": "agent_mcp_server",
            "use": "MCP status/search/read tools and resource refs",
        },
    ]
