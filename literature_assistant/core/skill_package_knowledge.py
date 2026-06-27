"""Read-only knowledge projection for repo-local Scholar AI Skill packages."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path used by the running app.
    from literature_assistant.core.project_paths import REPO_ROOT
    from literature_assistant.core.skills.user_manifest import (
        ManifestValidationError,
        parse_skill_md_frontmatter,
        validate_manifest,
    )
except ImportError:  # pragma: no cover - flat import path used by legacy tests.
    from project_paths import REPO_ROOT
    from skills.user_manifest import ManifestValidationError, parse_skill_md_frontmatter, validate_manifest


SKILL_PACKAGE_KNOWLEDGE_SCHEMA_VERSION = "scholar-ai-skill-package-knowledge/v1"
SKILL_PACKAGE_REF_SCHEMA_VERSION = "scholar-ai-skill-package-knowledge-ref/v1"
ACADEMIC_ENGLISH_SKILL_PACKAGE_ID = "academic-english-discourse"
SUPPORTED_SKILL_PACKAGE_IDS = frozenset({ACADEMIC_ENGLISH_SKILL_PACKAGE_ID})
MAX_SKILL_KNOWLEDGE_FILE_BYTES = 2 * 1024 * 1024
MAX_SKILL_PACKAGE_SEARCH_RESULTS = 50

_VALID_PACKAGE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
_KNOWLEDGE_SOURCE_GLOBS = (
    "SKILL.md",
    "references/*.md",
    "prompts/*.txt",
)


@dataclass(frozen=True)
class SkillPackageSource:
    """One source file loaded into the read-only Skill knowledge projection."""

    relative_path: str
    role: str
    loaded: bool
    content_hash: str
    char_count: int
    byte_count: int
    updated_at: str
    warning: str | None = None


@dataclass(frozen=True)
class SkillPackageChunk:
    """One stable chunk ref derived from a Skill package source file."""

    chunk_id: str
    package_id: str
    title: str
    source_path: str
    source_role: str
    source_hash: str
    content_hash: str
    span_start: int
    span_end: int
    text: str

    @property
    def ref_id(self) -> str:
        """Return the agent-readable resource ref for this chunk."""

        return build_skill_package_chunk_ref_id(self.package_id, self.chunk_id)

    @property
    def read_endpoint(self) -> str:
        """Return the bounded resource endpoint for this chunk."""

        return f"/api/agent-bridge/resource/{self.ref_id}"


@dataclass(frozen=True)
class SkillPackageSnapshot:
    """Read-only runtime status for one repo-local Skill package."""

    package_id: str
    package_root: str
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
    skill_kind: str
    source_files: list[SkillPackageSource] = field(default_factory=list)
    chunks: list[SkillPackageChunk] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    runtime_consumers: list[dict[str, str]] = field(default_factory=list)

    def to_status_payload(self, *, include_chunks: bool = False) -> dict[str, Any]:
        """Return a JSON-safe runtime status payload.

        Args:
            include_chunks: Whether to include chunk metadata. Chunk text is
                intentionally excluded from status payloads; agents read text
                through bounded resource refs.
        """

        payload: dict[str, Any] = {
            "schema_version": SKILL_PACKAGE_KNOWLEDGE_SCHEMA_VERSION,
            "package_id": self.package_id,
            "package_root": self.package_root,
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
            "skill_kind": self.skill_kind,
            "source_files": [asdict(item) for item in self.source_files],
            "chunk_count": len(self.chunks),
            "warnings": list(self.warnings),
            "manifest": dict(self.manifest),
            "runtime_consumers": [dict(item) for item in self.runtime_consumers],
        }
        if include_chunks:
            payload["chunks"] = [
                {
                    "chunk_id": chunk.chunk_id,
                    "ref_id": chunk.ref_id,
                    "read_endpoint": chunk.read_endpoint,
                    "title": chunk.title,
                    "source_path": chunk.source_path,
                    "source_role": chunk.source_role,
                    "source_hash": chunk.source_hash,
                    "content_hash": chunk.content_hash,
                    "span_start": chunk.span_start,
                    "span_end": chunk.span_end,
                    "char_count": len(chunk.text),
                }
                for chunk in self.chunks
            ]
        return payload


def skill_package_root(package_id: str) -> Path:
    """Return the repo-local root for a supported Skill package.

    Args:
        package_id: Stable Skill package id from `SUPPORTED_SKILL_PACKAGE_IDS`.

    Raises:
        ValueError: If the package id is empty, malformed, or unsupported.
    """

    normalized = _normalize_package_id(package_id)
    if normalized not in SUPPORTED_SKILL_PACKAGE_IDS:
        raise ValueError(f"Unsupported Skill package: {normalized}")
    return REPO_ROOT / "extension_packages" / "skills" / normalized


def build_skill_package_chunk_ref_id(package_id: str, chunk_id: str) -> str:
    """Return a stable agent resource ref for a Skill package chunk."""

    normalized_package_id = _normalize_package_id(package_id)
    normalized_chunk_id = str(chunk_id or "").strip()
    if not normalized_chunk_id:
        raise ValueError("chunk_id must not be empty")
    if any(ord(char) < 32 for char in normalized_chunk_id):
        raise ValueError("chunk_id must not contain control characters")
    return f"skill_package:{normalized_package_id}:chunk:{normalized_chunk_id}"


def load_skill_package_snapshot(package_id: str = ACADEMIC_ENGLISH_SKILL_PACKAGE_ID) -> SkillPackageSnapshot:
    """Load one repo-local Skill package as a read-only knowledge snapshot."""

    normalized = _normalize_package_id(package_id)
    root = skill_package_root(normalized)
    skill_md = root / "SKILL.md"
    package_root_ref = _repo_relative(root)
    source_path_ref = _repo_relative(skill_md)
    warnings: list[str] = []

    if not skill_md.exists():
        warnings.append(f"SKILL.md is missing for Skill package {normalized}.")
        return SkillPackageSnapshot(
            package_id=normalized,
            package_root=package_root_ref,
            source_path=source_path_ref,
            source_hash="unknown",
            content_hash="unknown",
            loaded=False,
            manifest_loaded=False,
            load_status="missing",
            updated_at="unknown",
            title=normalized,
            description="",
            version="unknown",
            skill_kind="unknown",
            warnings=warnings,
            runtime_consumers=_runtime_consumers(),
        )

    source_files = _discover_knowledge_sources(root)
    file_payloads: list[tuple[Path, str, str]] = []
    source_records: list[SkillPackageSource] = []
    for source_file in source_files:
        role = _source_role(root, source_file)
        try:
            text = _read_bounded_source(source_file)
            file_payloads.append((source_file, role, text))
            source_records.append(_source_record(root, source_file, role, text=text))
        except OSError as exc:
            warnings.append(f"Could not read {source_file.name}: {exc}")
            source_records.append(_source_record(root, source_file, role, text="", warning=str(exc)))

    skill_text = next((text for path, _role, text in file_payloads if path == skill_md), "")
    source_hash = _sha256_text(skill_text) if skill_text else "unknown"
    manifest_loaded = False
    manifest: dict[str, Any] = {}
    title = normalized
    description = ""
    version = "unknown"
    skill_kind = "unknown"
    if skill_text:
        frontmatter = parse_skill_md_frontmatter(skill_text)
        if frontmatter:
            try:
                parsed_manifest = validate_manifest(frontmatter)
                manifest_loaded = True
                manifest = {
                    "id": parsed_manifest.id,
                    "name": parsed_manifest.name,
                    "version": parsed_manifest.version,
                    "kind": parsed_manifest.kind,
                    "description": parsed_manifest.description,
                    "entry_mode": parsed_manifest.entry_mode,
                    "ui_visibility": parsed_manifest.ui_visibility,
                    "supported_scopes": list(parsed_manifest.supported_scopes),
                    "permissions": dict(parsed_manifest.permissions),
                    "root_policy": dict(parsed_manifest.root_policy),
                    "script_policy": dict(parsed_manifest.script_policy),
                    "model_policy": dict(parsed_manifest.model_policy),
                    "privacy_notes": parsed_manifest.privacy_notes,
                    "rollback_hint": parsed_manifest.rollback_hint,
                    "tags": list(parsed_manifest.tags),
                    "display_group": parsed_manifest.display_group,
                    "experimental": parsed_manifest.experimental,
                    "high_risk_flags": list(parsed_manifest.high_risk_flags),
                }
                title = parsed_manifest.name
                description = parsed_manifest.description
                version = parsed_manifest.version
                skill_kind = parsed_manifest.kind
            except ManifestValidationError as exc:
                warnings.extend(exc.errors)
                manifest = {"raw_frontmatter": dict(frontmatter), "validation_errors": list(exc.errors)}
        else:
            warnings.append("SKILL.md has no valid frontmatter.")

    chunks = _build_chunks(normalized, root, file_payloads)
    content_hash = _combined_content_hash(file_payloads) if file_payloads else "unknown"
    loaded = bool(skill_text and manifest_loaded and chunks)
    load_status = "loaded" if loaded else "missing"
    return SkillPackageSnapshot(
        package_id=normalized,
        package_root=package_root_ref,
        source_path=source_path_ref,
        source_hash=source_hash,
        content_hash=content_hash,
        loaded=loaded,
        manifest_loaded=manifest_loaded,
        load_status=load_status,
        updated_at=_latest_updated_at([path for path, _role, _text in file_payloads]),
        title=title,
        description=description,
        version=version,
        skill_kind=skill_kind,
        source_files=source_records,
        chunks=chunks,
        manifest=manifest,
        warnings=warnings,
        runtime_consumers=_runtime_consumers(),
    )


def get_skill_package_status(package_id: str = ACADEMIC_ENGLISH_SKILL_PACKAGE_ID) -> dict[str, Any]:
    """Return the read-only status payload for one Skill knowledge package."""

    return load_skill_package_snapshot(package_id).to_status_payload(include_chunks=True)


def search_skill_package(package_id: str, query: str, *, top_k: int = 8) -> list[dict[str, Any]]:
    """Search a read-only Skill package and return bounded resource refs.

    Args:
        package_id: Supported repo-local Skill package id.
        query: Search text. Empty queries are rejected.
        top_k: Maximum number of refs to return.
    """

    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise ValueError("query must not be empty")
    if top_k < 1 or top_k > MAX_SKILL_PACKAGE_SEARCH_RESULTS:
        raise ValueError(f"top_k must be between 1 and {MAX_SKILL_PACKAGE_SEARCH_RESULTS}")

    snapshot = load_skill_package_snapshot(package_id)
    terms = _query_terms(normalized_query)
    hits: list[tuple[int, SkillPackageChunk]] = []
    for chunk in snapshot.chunks:
        score = _score_chunk(chunk, terms, normalized_query)
        if score > 0:
            hits.append((score, chunk))
    hits.sort(key=lambda item: (-item[0], item[1].source_path, item[1].span_start))

    return [
        {
            "schema_version": SKILL_PACKAGE_REF_SCHEMA_VERSION,
            "ref_id": chunk.ref_id,
            "kind": "skill_package",
            "resource_kind": "chunk",
            "title": chunk.title,
            "summary": _summary_for_query(chunk.text, terms),
            "score": float(score),
            "rank": index,
            "read_endpoint": chunk.read_endpoint,
            "metadata": _chunk_metadata(chunk, snapshot),
        }
        for index, (score, chunk) in enumerate(hits[:top_k], start=1)
    ]


def read_skill_package_resource(raw_ref: str) -> dict[str, Any]:
    """Resolve one `skill_package:<package_id>:chunk:<chunk_id>` resource ref."""

    package_id, chunk_id = _parse_skill_package_raw_ref(raw_ref)
    snapshot = load_skill_package_snapshot(package_id)
    for chunk in snapshot.chunks:
        if chunk.chunk_id == chunk_id:
            return {
                "kind": "skill_package",
                "project_id": None,
                "title": chunk.title,
                "content": chunk.text,
                "metadata": _chunk_metadata(chunk, snapshot),
                "ref_id": chunk.ref_id,
            }
    raise KeyError(f"Skill package chunk not found: {chunk_id}")


def _normalize_package_id(package_id: str) -> str:
    normalized = str(package_id or "").strip().lower()
    if not normalized:
        raise ValueError("package_id must not be empty")
    if not _VALID_PACKAGE_ID_RE.fullmatch(normalized):
        raise ValueError(f"Invalid Skill package id: {package_id}")
    return normalized


def _discover_knowledge_sources(root: Path) -> list[Path]:
    sources: list[Path] = []
    for pattern in _KNOWLEDGE_SOURCE_GLOBS:
        for path in sorted(root.glob(pattern), key=lambda item: item.as_posix()):
            if path.is_file() and path not in sources:
                sources.append(path)
    return sources


def _read_bounded_source(path: Path) -> str:
    size = path.stat().st_size
    if size > MAX_SKILL_KNOWLEDGE_FILE_BYTES:
        raise OSError(f"file exceeds {MAX_SKILL_KNOWLEDGE_FILE_BYTES} bytes")
    return path.read_text(encoding="utf-8")


def _source_role(root: Path, path: Path) -> str:
    relative = path.relative_to(root).as_posix()
    if relative == "SKILL.md":
        return "manifest"
    if relative.startswith("references/"):
        return "reference"
    if relative.startswith("prompts/"):
        return "prompt"
    return "supporting_source"


def _source_record(root: Path, path: Path, role: str, *, text: str, warning: str | None = None) -> SkillPackageSource:
    loaded = warning is None and bool(text)
    return SkillPackageSource(
        relative_path=path.relative_to(root).as_posix(),
        role=role,
        loaded=loaded,
        content_hash=_sha256_text(text) if loaded else "unknown",
        char_count=len(text) if loaded else 0,
        byte_count=len(text.encode("utf-8")) if loaded else 0,
        updated_at=_path_updated_at(path) if path.exists() else "unknown",
        warning=warning,
    )


def _build_chunks(package_id: str, root: Path, file_payloads: list[tuple[Path, str, str]]) -> list[SkillPackageChunk]:
    chunks: list[SkillPackageChunk] = []
    for path, role, text in file_payloads:
        if not text.strip():
            continue
        relative_path = path.relative_to(root).as_posix()
        source_hash = _sha256_text(text)
        title = _title_from_text(text, fallback=Path(relative_path).stem)
        chunk_id = _chunk_id(package_id, relative_path, 0, len(text))
        chunks.append(
            SkillPackageChunk(
                chunk_id=chunk_id,
                package_id=package_id,
                title=title,
                source_path=relative_path,
                source_role=role,
                source_hash=source_hash,
                content_hash=source_hash,
                span_start=0,
                span_end=len(text),
                text=text.strip(),
            )
        )
    return chunks


def _chunk_id(package_id: str, relative_path: str, span_start: int, span_end: int) -> str:
    digest = hashlib.sha256(f"{package_id}:{relative_path}:{span_start}:{span_end}".encode("utf-8")).hexdigest()
    stem = Path(relative_path).stem.lower().replace("_", "-")
    safe_stem = re.sub(r"[^a-z0-9.-]+", "-", stem).strip("-") or "source"
    return f"{safe_stem}-{digest[:16]}"


def _chunk_metadata(chunk: SkillPackageChunk, snapshot: SkillPackageSnapshot) -> dict[str, Any]:
    return {
        "knowledge_ref_schema_version": SKILL_PACKAGE_REF_SCHEMA_VERSION,
        "ref_id": chunk.ref_id,
        "package_id": chunk.package_id,
        "resource_kind": "chunk",
        "source": "skill_package",
        "source_type": "skill_package",
        "source_path": chunk.source_path,
        "source_role": chunk.source_role,
        "source_hash": chunk.source_hash,
        "content_hash": chunk.content_hash,
        "package_content_hash": snapshot.content_hash,
        "span_start": chunk.span_start,
        "span_end": chunk.span_end,
        "read_endpoint": chunk.read_endpoint,
        "runtime_consumers": [dict(item) for item in snapshot.runtime_consumers],
    }


def _parse_skill_package_raw_ref(raw_ref: str) -> tuple[str, str]:
    normalized = str(raw_ref or "").strip()
    parts = normalized.split(":")
    if len(parts) != 3 or parts[1] != "chunk":
        raise ValueError("skill_package refs must use <package_id>:chunk:<chunk_id>")
    package_id = _normalize_package_id(parts[0])
    chunk_id = parts[2].strip()
    if not chunk_id:
        raise ValueError("skill_package chunk id is required")
    if any(ord(char) < 32 for char in chunk_id):
        raise ValueError("skill_package chunk id must not contain control characters")
    return package_id, chunk_id


def _query_terms(query: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", query.lower())
    return [term for term in terms if term]


def _score_chunk(chunk: SkillPackageChunk, terms: list[str], query: str) -> int:
    text = chunk.text.lower()
    title = chunk.title.lower()
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


def _title_from_text(text: str, *, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            if title:
                return title[:300]
    return fallback.replace("-", " ").replace("_", " ").strip().title() or "Skill Package Source"


def _combined_content_hash(file_payloads: list[tuple[Path, str, str]]) -> str:
    payload = [
        {
            "relative_path": _repo_relative(path),
            "role": role,
            "content_hash": _sha256_text(text),
        }
        for path, role, text in file_payloads
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _latest_updated_at(paths: list[Path]) -> str:
    timestamps = [path.stat().st_mtime for path in paths if path.exists()]
    if not timestamps:
        return "unknown"
    return datetime.fromtimestamp(max(timestamps), tz=timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


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
            "consumer": "literature_assistant.core.routers.knowledge_router",
            "use": "read-only package registry and skill-package search",
        },
        {
            "consumer": "literature_assistant.core.routers.agent_bridge_router",
            "use": "bounded resource loading through agent_resource_read",
        },
        {
            "consumer": "literature.skill_package_status",
            "use": "MCP read-only provenance/status inspection",
        },
        {
            "consumer": "literature.skill_package_search",
            "use": "MCP refs-only retrieval before bounded resource loading",
        },
    ]
