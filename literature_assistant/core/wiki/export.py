from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import yaml

from literature_assistant.core.wiki.graph import WikiGraphSnapshot
from literature_assistant.core.wiki.page_store import AUTO_END, AUTO_START, atomic_write_text, WikiPageStore

_WIKI_EXPORT_MANIFEST_NAME = "manifest.json"
_OKF_VERSION = "0.1"
_OKF_PROFILE_SCHEMA_VERSION = "scholar-ai-okf-profile/v1"
_OKF_BUNDLE_MANIFEST_SCHEMA_VERSION = "scholar-ai-okf-bundle-manifest/v1"
_OKF_TYPE_WIKI_PAGE = "scholar-ai-wiki-page"
_OKF_RESERVED_MARKDOWN_NAMES = frozenset({"index.md", "log.md"})
_OKF_PROJECT_RECORD_GROUPS: dict[str, dict[str, Any]] = {
    "materials": {
        "folder": "materials",
        "type": "scholar-ai-material",
        "id_keys": ("material_id", "id", "ref_id"),
    },
    "evidence": {
        "folder": "evidence",
        "type": "scholar-ai-evidence",
        "id_keys": ("evidence_pack_ref", "evidence_ref", "ref_id", "chunk_id", "id"),
    },
    "answers": {
        "folder": "answers",
        "type": "scholar-ai-answer",
        "id_keys": ("conversation_id", "node_id", "run_id", "request_id", "id"),
    },
    "tasks": {
        "folder": "tasks",
        "type": "scholar-ai-task",
        "id_keys": ("task_id", "request_id", "job_id", "id"),
    },
    "reviews": {
        "folder": "reviews",
        "type": "scholar-ai-review",
        "id_keys": ("item_id", "review_id", "page_path", "id"),
    },
    "exports": {
        "folder": "exports",
        "type": "scholar-ai-export",
        "id_keys": ("export_id", "artifact_id", "filename", "id"),
    },
}
_OKF_PRIVATE_TEXT_KEYS = frozenset({
    "base64",
    "binary",
    "body",
    "chunk_text",
    "content",
    "content_text",
    "document_text",
    "embedding",
    "full_text",
    "provider_payload",
    "raw_provider_payload",
    "raw_text",
    "text",
})
_OKF_PRIVATE_PATH_KEYS = frozenset({
    "allowed_root",
    "asset_path",
    "file_path",
    "private_path_ref",
    "source_path",
    "trace_path",
    "zotero_data_dir",
})
_OKF_SECRET_KEY_RE = re.compile(r"(api[_-]?key|authorization|bearer|cookie|password|secret|token)", re.IGNORECASE)
_OKF_PRIVATE_PATH_RE = re.compile(
    r"(^[A-Za-z]:[\\/]|^\\\\|^/(?:Users|home|var|tmp|private|Volumes)/)",
    re.IGNORECASE,
)
_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def export_graph_json(snapshot: WikiGraphSnapshot) -> dict[str, Any]:
    """Return a deterministic graph export payload for UI/debug consumers."""

    if not isinstance(snapshot, WikiGraphSnapshot):
        raise TypeError("snapshot must be a WikiGraphSnapshot")
    return snapshot.to_dict()


def write_graph_json_export(snapshot: WikiGraphSnapshot, output_path: Path) -> None:
    """Write a graph JSON export without mutating source wiki pages."""

    if not isinstance(output_path, Path):
        output_path = Path(output_path)
    if output_path.is_dir():
        raise ValueError("output_path must be a file path")
    payload = json.dumps(export_graph_json(snapshot), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_text(output_path, payload)


def _build_wiki_export_bundle_manifest(pages: list[dict[str, Any]], output_path: Path) -> dict[str, Any]:
    """Build an inspectable manifest for a wiki Markdown export archive.

    Args:
        pages: Exported Markdown page records with path and byte metadata.
        output_path: Target archive path used for provenance only.

    Returns:
        JSON-safe manifest for the archive contents.

    Raises:
        ValueError: If page records have invalid shapes.
    """
    if not isinstance(output_path, Path):
        output_path = Path(output_path)
    resources: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, dict):
            raise ValueError("page records must be objects")
        page_path = str(page.get("path") or "").strip()
        if not page_path:
            raise ValueError("page path must not be empty")
        resources.append(
            {
                "role": "wiki_page",
                "path": page_path,
                "format": "markdown",
                "media_type": "text/markdown",
                "byte_count": page.get("byte_count", 0),
            }
        )

    return {
        "schema_version": "wiki_export_bundle_manifest_v1",
        "bundle": {
            "kind": "wiki_markdown_page_bundle",
            "entry_document": None,
            "archive_filename": output_path.name,
            "manifest": _WIKI_EXPORT_MANIFEST_NAME,
        },
        "counts": {
            "pages": len(pages),
            "resources": len(resources),
        },
        "pages": list(pages),
        "resources": resources,
    }


def _ensure_page_store_protocol(page_store: Any) -> None:
    """Validate the read-only page-store protocol across legacy import paths."""

    if page_store is None:
        raise TypeError("page_store is required")
    if not callable(getattr(page_store, "list_pages", None)):
        raise TypeError("page_store must expose list_pages()")
    if not callable(getattr(page_store, "read_page", None)):
        raise TypeError("page_store must expose read_page(relative_path)")


def _utc_now_iso() -> str:
    """Return a timezone-aware UTC timestamp for reproducible export metadata."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _strip_wiki_auto_markers(body: str) -> str:
    """Remove Scholar AI managed markers before writing portable OKF bodies."""

    if not isinstance(body, str):
        raise TypeError("body must be a string")
    kept_lines = [
        line
        for line in body.splitlines()
        if line.strip() not in {AUTO_START, AUTO_END}
    ]
    return "\n".join(kept_lines).strip()


def _split_wiki_json_frontmatter(content: str) -> tuple[dict[str, Any], str, list[str]]:
    """Split the current Wiki JSON frontmatter format without mutating pages.

    Args:
        content: Markdown content as stored by ``WikiPageStore``.

    Returns:
        A tuple of ``frontmatter``, cleaned body, and non-fatal warnings.
    """

    if not isinstance(content, str):
        raise TypeError("content must be a string")
    warnings: list[str] = []
    if not content.startswith("---json\n"):
        warnings.append("wiki page has no JSON frontmatter; OKF metadata was derived from path/body")
        return {}, _strip_wiki_auto_markers(content), warnings

    terminator = "\n---\n"
    end_index = content.find(terminator, len("---json\n"))
    if end_index == -1:
        warnings.append("wiki page JSON frontmatter terminator is missing; OKF metadata was derived from body")
        return {}, _strip_wiki_auto_markers(content), warnings

    raw_frontmatter = content[len("---json\n") : end_index]
    body = content[end_index + len(terminator) :]
    try:
        payload = json.loads(raw_frontmatter)
    except json.JSONDecodeError:
        warnings.append("wiki page JSON frontmatter is invalid; OKF metadata was derived from path/body")
        return {}, _strip_wiki_auto_markers(body), warnings
    if not isinstance(payload, dict):
        warnings.append("wiki page JSON frontmatter is not an object; OKF metadata was derived from path/body")
        return {}, _strip_wiki_auto_markers(body), warnings
    return payload, _strip_wiki_auto_markers(body), warnings


def _json_safe(value: Any) -> Any:
    """Coerce metadata to YAML/JSON-safe shapes while preserving unknown fields."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _first_body_summary(body: str, *, limit: int = 240) -> str:
    """Return a bounded one-line summary for OKF previews."""

    if not isinstance(body, str):
        raise TypeError("body must be a string")
    for line in body.splitlines():
        normalized = re.sub(r"\s+", " ", line.strip()).strip()
        if not normalized:
            continue
        if normalized.startswith("#"):
            normalized = normalized.lstrip("#").strip()
        if normalized:
            return normalized[:limit]
    return ""


def _string_list(value: Any) -> list[str]:
    """Normalize tag-like metadata into a deduplicated string list."""

    values: list[str] = []
    if isinstance(value, str):
        values.extend(part.strip() for part in re.split(r"[,/]", value) if part.strip())
    elif isinstance(value, (list, tuple, set)):
        values.extend(str(item).strip() for item in value if str(item).strip())
    deduped: dict[str, str] = {}
    for item in values:
        deduped.setdefault(item.lower(), item)
    return list(deduped.values())


def _okf_tags_from_frontmatter(frontmatter: Mapping[str, Any]) -> list[str]:
    """Derive OKF tags from existing Wiki metadata."""

    tags: list[str] = []
    for key in ("tags", "labels", "kind", "status"):
        tags.extend(_string_list(frontmatter.get(key)))
    deduped: dict[str, str] = {}
    for tag in tags:
        deduped.setdefault(tag.lower(), tag)
    return list(deduped.values())


def _okf_title(relative_path: Path, frontmatter: Mapping[str, Any]) -> str:
    """Return a stable OKF display title for one Wiki page."""

    raw_title = frontmatter.get("title")
    if isinstance(raw_title, str) and raw_title.strip():
        return raw_title.strip()
    return relative_path.stem.replace("_", " ").replace("-", " ").strip() or "Untitled Wiki Page"


def _okf_description(frontmatter: Mapping[str, Any], body: str) -> str:
    """Return an OKF description without exposing full page text."""

    for key in ("description", "summary"):
        raw_value = frontmatter.get(key)
        if isinstance(raw_value, str) and raw_value.strip():
            return re.sub(r"\s+", " ", raw_value.strip())[:240]
    return _first_body_summary(body)


def _render_yaml_frontmatter(frontmatter: Mapping[str, Any]) -> str:
    """Render YAML frontmatter for OKF-facing markdown documents."""

    if not isinstance(frontmatter, Mapping):
        raise TypeError("frontmatter must be a mapping")
    payload = yaml.safe_dump(
        dict(frontmatter),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).strip()
    return f"---\n{payload}\n---\n"


def _render_okf_document(frontmatter: Mapping[str, Any], body: str) -> str:
    """Render one OKF concept document."""

    if not isinstance(body, str):
        raise TypeError("body must be a string")
    rendered_body = body.strip()
    if not rendered_body:
        rendered_body = f"# {frontmatter.get('title') or 'Untitled Wiki Page'}"
    return f"{_render_yaml_frontmatter(frontmatter)}\n{rendered_body}\n"


def _build_okf_wiki_frontmatter(
    relative_path: Path,
    source_frontmatter: Mapping[str, Any],
    body: str,
    *,
    generated_at_iso: str,
    project_id: str | None,
) -> dict[str, Any]:
    """Build Scholar AI's OKF-compatible profile for one wiki page."""

    if not isinstance(relative_path, Path):
        relative_path = Path(relative_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("relative_path must stay inside the wiki root")
    if not isinstance(source_frontmatter, Mapping):
        raise TypeError("source_frontmatter must be a mapping")
    if not isinstance(generated_at_iso, str) or not generated_at_iso.strip():
        raise ValueError("generated_at_iso must be a non-empty string")
    title = _okf_title(relative_path, source_frontmatter)
    description = _okf_description(source_frontmatter, body)
    timestamp = source_frontmatter.get("updated_at_iso") or source_frontmatter.get("timestamp") or generated_at_iso
    frontmatter: dict[str, Any] = {
        "type": _OKF_TYPE_WIKI_PAGE,
        "title": title,
        "description": description,
        "resource": f"scholar-ai://wiki/{relative_path.as_posix()}",
        "tags": _okf_tags_from_frontmatter(source_frontmatter),
        "timestamp": str(timestamp),
        "schema_version": _OKF_PROFILE_SCHEMA_VERSION,
        "okf_version": _OKF_VERSION,
        "wiki_path": relative_path.as_posix(),
    }
    if project_id:
        frontmatter["project_id"] = project_id
    for key in ("kind", "status", "evidence_refs", "source_hashes"):
        if key in source_frontmatter:
            frontmatter[f"wiki_{key}" if key in {"kind", "status"} else key] = _json_safe(source_frontmatter[key])
    if source_frontmatter:
        frontmatter["scholar_ai_frontmatter"] = _json_safe(source_frontmatter)
    return frontmatter


def _normalize_okf_record_id(value: Any, *, fallback: str) -> str:
    """Return a bundle-safe concept id segment for one process artifact.

    Args:
        value: Candidate id from a process artifact record.
        fallback: Non-empty id used when the record has no stable id.

    Returns:
        Filesystem-safe id segment suitable for an OKF archive member path.
    """

    candidate = str(value or "").strip() or fallback
    if not candidate.strip():
        raise ValueError("fallback must be non-empty")
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", candidate).strip(".-_")
    return normalized[:120] or fallback


def _first_record_value(record: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first non-empty value from a record for stable metadata derivation."""

    if not isinstance(record, Mapping):
        raise TypeError("record must be a mapping")
    for key in keys:
        value = record.get(key)
        if value not in (None, "", []):
            return value
    return None


def _record_title(group: str, record: Mapping[str, Any], record_id: str) -> str:
    """Return a human-readable title for one process artifact record."""

    for key in ("title", "name", "filename", "label", "query", "topic", "task_goal"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return re.sub(r"\s+", " ", value.strip())[:160]
    group_title = group[:-1] if group.endswith("s") else group
    return f"{group_title.replace('_', ' ').title()} {record_id}"


def _record_description(record: Mapping[str, Any]) -> str:
    """Return a bounded non-private summary without using raw full text fields."""

    for key in ("description", "summary", "abstract", "preview", "snippet", "status_message", "next_action"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return re.sub(r"\s+", " ", value.strip())[:240]
    status = record.get("status")
    if isinstance(status, str) and status.strip():
        return f"Status: {status.strip()[:120]}"
    return "No safe summary exported."


def _looks_like_private_path(value: str) -> bool:
    """Return true for local absolute paths that should not enter OKF summaries."""

    if not isinstance(value, str):
        raise TypeError("value must be a string")
    return bool(_OKF_PRIVATE_PATH_RE.search(value.strip()))


def _sanitize_okf_record_value(
    value: Any,
    *,
    key_path: str,
    redactions: list[dict[str, str]],
) -> Any:
    """Return a YAML-safe metadata value with private content removed.

    Args:
        value: Arbitrary process artifact metadata.
        key_path: Dot path used for redaction audit entries.
        redactions: Mutable list receiving redaction reason records.

    Returns:
        JSON/YAML-safe value, or ``None`` when the value must be omitted.
    """

    if not isinstance(key_path, str) or not key_path.strip():
        raise ValueError("key_path must be non-empty")
    key_name = key_path.rsplit(".", 1)[-1].lower()
    if _OKF_SECRET_KEY_RE.search(key_name):
        redactions.append({"path": key_path, "reason": "secret_key"})
        return None
    if key_name in _OKF_PRIVATE_TEXT_KEYS:
        redactions.append({"path": key_path, "reason": "private_text"})
        return None
    if key_name in _OKF_PRIVATE_PATH_KEYS:
        redactions.append({"path": key_path, "reason": "private_path"})
        return None

    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        normalized = re.sub(r"\s+", " ", value.strip())
        if _looks_like_private_path(normalized):
            redactions.append({"path": key_path, "reason": "private_path"})
            return None
        return normalized[:500]
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for child_key, child_value in value.items():
            child_path = f"{key_path}.{child_key}"
            sanitized_value = _sanitize_okf_record_value(child_value, key_path=child_path, redactions=redactions)
            if sanitized_value is not None:
                sanitized[str(child_key)] = sanitized_value
        return sanitized
    if isinstance(value, (list, tuple, set)):
        sanitized_items: list[Any] = []
        for index, item in enumerate(value):
            sanitized_item = _sanitize_okf_record_value(item, key_path=f"{key_path}[{index}]", redactions=redactions)
            if sanitized_item is not None:
                sanitized_items.append(sanitized_item)
            if len(sanitized_items) >= 50:
                redactions.append({"path": key_path, "reason": "list_truncated"})
                break
        return sanitized_items
    return str(value)[:500]


def _sanitize_okf_record(record: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Return a redacted process artifact record and its audit redactions."""

    if not isinstance(record, Mapping):
        raise TypeError("record must be a mapping")
    redactions: list[dict[str, str]] = []
    sanitized: dict[str, Any] = {}
    for key, value in record.items():
        sanitized_value = _sanitize_okf_record_value(value, key_path=str(key), redactions=redactions)
        if sanitized_value is not None:
            sanitized[str(key)] = sanitized_value
    return sanitized, redactions


def _record_tags(group: str, record: Mapping[str, Any]) -> list[str]:
    """Build stable OKF tags for one process artifact concept."""

    tags = [f"scholar-ai:{group}", "process-artifact"]
    for key in ("tags", "labels", "status", "kind", "source"):
        tags.extend(_string_list(record.get(key)))
    deduped: dict[str, str] = {}
    for tag in tags:
        deduped.setdefault(tag.lower(), tag)
    return list(deduped.values())


def _record_timestamp(record: Mapping[str, Any], generated_at_iso: str) -> str:
    """Return a meaningful timestamp for one process artifact concept."""

    for key in ("updated_at", "updated_at_iso", "created_at", "started_at", "finished_at", "timestamp"):
        value = record.get(key)
        if value not in (None, "", []):
            return str(value)
    return generated_at_iso


def _build_okf_project_record_document(
    group: str,
    record: Mapping[str, Any],
    index: int,
    *,
    project_id: str | None,
    generated_at_iso: str,
) -> tuple[str, str, dict[str, Any]]:
    """Build one OKF document from an explicit Scholar AI process artifact record."""

    if group not in _OKF_PROJECT_RECORD_GROUPS:
        raise ValueError(f"unsupported OKF project record group: {group}")
    if not isinstance(record, Mapping):
        raise TypeError("project artifact records must be mappings")
    if index < 0:
        raise ValueError("index must be non-negative")

    config = _OKF_PROJECT_RECORD_GROUPS[group]
    record_id = _normalize_okf_record_id(
        _first_record_value(record, tuple(config["id_keys"])),
        fallback=f"{group}-{index + 1}",
    )
    folder = str(config["folder"])
    okf_path = f"{folder}/{record_id}.md"
    title = _record_title(group, record, record_id)
    description = _record_description(record)
    sanitized_record, redactions = _sanitize_okf_record(record)

    frontmatter: dict[str, Any] = {
        "type": str(config["type"]),
        "title": title,
        "description": description,
        "resource": f"scholar-ai://{group}/{record_id}",
        "tags": _record_tags(group, record),
        "timestamp": _record_timestamp(record, generated_at_iso),
        "schema_version": _OKF_PROFILE_SCHEMA_VERSION,
        "okf_version": _OKF_VERSION,
        "scholar_ai_group": group,
        "scholar_ai_record_id": record_id,
        "scholar_ai_record": _json_safe(sanitized_record),
    }
    if project_id:
        frontmatter["project_id"] = project_id
    for id_key in config["id_keys"]:
        if id_key in sanitized_record and sanitized_record[id_key] not in (None, "", []):
            frontmatter[str(id_key)] = _json_safe(sanitized_record[id_key])
    if redactions:
        frontmatter["scholar_ai_redactions"] = redactions

    body_lines = [
        f"# {title}",
        "",
        description,
        "",
        "## Safe Metadata",
        "",
        "```json",
        json.dumps(_json_safe(sanitized_record), ensure_ascii=False, indent=2, sort_keys=True),
        "```",
    ]
    if redactions:
        body_lines.extend(
            [
                "",
                "## Redactions",
                "",
                "```json",
                json.dumps(redactions, ensure_ascii=False, indent=2, sort_keys=True),
                "```",
            ]
        )
    text = _render_okf_document(frontmatter, "\n".join(body_lines).strip())
    return okf_path, text, frontmatter


def _render_okf_project_log(*, generated_at_iso: str, concept_count: int, group_counts: Mapping[str, int]) -> str:
    """Render an OKF log for a process artifact export."""

    if concept_count < 0:
        raise ValueError("concept_count must be non-negative")
    date_part = generated_at_iso[:10]
    groups = ", ".join(f"{group}={count}" for group, count in sorted(group_counts.items()))
    return (
        "# Scholar AI Project Artifact OKF Export Log\n\n"
        f"## {date_part}\n"
        f"* **Export**: Created a local Scholar AI process artifact OKF bundle with {concept_count} concept documents.\n"
        f"* **Groups**: {groups or 'none'}.\n"
        "* **Privacy**: Raw full text, private absolute paths, secrets, and provider payloads were redacted by default.\n"
    )


def export_project_artifact_okf_bundle(
    records_by_group: Mapping[str, list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...]],
    output_path: Path,
    *,
    project_id: str | None = None,
    generated_at_iso: str | None = None,
) -> dict[str, Any]:
    """Export explicit Scholar AI process artifact records as a local OKF zip bundle.

    Args:
        records_by_group: Mapping from supported process artifact groups
            (``materials``, ``evidence``, ``answers``, ``tasks``, ``reviews``,
            ``exports``) to explicit metadata records. The exporter does not
            read project stores, Zotero, chat history, or external services.
        output_path: Local ``.zip`` archive path to write.
        project_id: Optional Scholar AI project id added to frontmatter.
        generated_at_iso: Optional deterministic timestamp for tests.

    Returns:
        Export result with archive path, concept counts, validation warnings,
        and manifest metadata.

    Raises:
        TypeError: If inputs do not match the explicit-record contract.
        ValueError: If ``output_path`` or group names are unsafe.
    """

    if not isinstance(records_by_group, Mapping):
        raise TypeError("records_by_group must be a mapping")
    if not isinstance(output_path, Path):
        output_path = Path(output_path)
    if output_path.is_dir():
        raise ValueError("output_path must be a file path, not a directory")
    if output_path.suffix.lower() != ".zip":
        raise ValueError("output_path must end with .zip")
    if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
        raise ValueError("project_id must be a non-empty string when provided")

    normalized_project_id = project_id.strip() if project_id else None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = generated_at_iso or _utc_now_iso()
    errors: list[str] = []
    warnings: list[str] = []
    entries: list[tuple[str, str, dict[str, Any]]] = []
    group_counts = {group: 0 for group in _OKF_PROJECT_RECORD_GROUPS}

    for group, records in records_by_group.items():
        if group not in _OKF_PROJECT_RECORD_GROUPS:
            raise ValueError(f"unsupported OKF project record group: {group}")
        if not isinstance(records, (list, tuple)):
            raise TypeError(f"{group} records must be a list or tuple")
        for index, record in enumerate(records):
            try:
                okf_path, text, frontmatter = _build_okf_project_record_document(
                    str(group),
                    record,
                    index,
                    project_id=normalized_project_id,
                    generated_at_iso=generated_at,
                )
                entries.append((okf_path, text, frontmatter))
                group_counts[str(group)] += 1
            except Exception as exc:
                errors.append(f"Failed to convert {group}[{index}]: {exc}")

    known_paths = {"index.md", "log.md", *[path for path, _text, _frontmatter in entries]}
    concepts: list[dict[str, Any]] = []
    for okf_path, text, frontmatter in entries:
        validation = validate_okf_markdown_document(okf_path, text, known_paths=known_paths)
        errors.extend(f"{okf_path}: {error}" for error in validation["errors"])
        warnings.extend(f"{okf_path}: {warning}" for warning in validation["warnings"])
        concepts.append(
            {
                "path": okf_path,
                "type": frontmatter.get("type"),
                "title": frontmatter.get("title"),
                "description": frontmatter.get("description"),
                "group": frontmatter.get("scholar_ai_group"),
                "record_id": frontmatter.get("scholar_ai_record_id"),
                "byte_count": len(text.encode("utf-8")),
            }
        )

    manifest = _build_okf_bundle_manifest(
        concepts,
        output_path,
        generated_at_iso=generated_at,
        warnings=warnings,
    )
    manifest["bundle"]["profile"] = "scholar_ai_project_artifacts"
    manifest["counts"]["groups"] = {group: count for group, count in group_counts.items() if count}
    manifest["record_groups"] = {
        group: {
            "folder": str(config["folder"]),
            "type": str(config["type"]),
            "count": group_counts[group],
        }
        for group, config in _OKF_PROJECT_RECORD_GROUPS.items()
    }

    try:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("index.md", _render_okf_root_index(concepts, generated_at_iso=generated_at))
            zf.writestr(
                "log.md",
                _render_okf_project_log(
                    generated_at_iso=generated_at,
                    concept_count=len(concepts),
                    group_counts={group: count for group, count in group_counts.items() if count},
                ),
            )
            for okf_path, text, _frontmatter in entries:
                zf.writestr(okf_path, text)
            zf.writestr(
                _WIKI_EXPORT_MANIFEST_NAME,
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
    except Exception as exc:
        return {
            "success": False,
            "page_count": 0,
            "output_path": str(output_path),
            "errors": [f"OKF project artifact export failed: {exc}"],
            "warnings": warnings,
            "manifest": manifest,
        }

    return {
        "success": len(errors) == 0,
        "page_count": len(concepts),
        "output_path": str(output_path),
        "errors": errors,
        "warnings": warnings,
        "manifest": manifest,
    }


def parse_okf_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse a Markdown document with OKF YAML frontmatter.

    Args:
        text: UTF-8 Markdown text containing a leading YAML frontmatter block.

    Returns:
        Parsed frontmatter mapping and Markdown body.

    Raises:
        ValueError: If the frontmatter block is missing, unterminated, invalid,
            or does not decode to a mapping.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("OKF document must start with YAML frontmatter")
    end_index: int | None = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        raise ValueError("OKF frontmatter terminator not found")
    raw_frontmatter = "\n".join(lines[1:end_index])
    try:
        payload = yaml.safe_load(raw_frontmatter) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"OKF frontmatter YAML is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("OKF frontmatter must decode to an object")
    body = "\n".join(lines[end_index + 1 :])
    return payload, body.lstrip("\n")


def _normalize_archive_member_name(value: str) -> str:
    """Validate a zip member path before treating it as local bundle content."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("archive member path cannot be empty")
    if "\\" in value:
        raise ValueError("archive member paths must use forward slashes")
    if any(ord(char) < 32 for char in value):
        raise ValueError("archive member path contains control characters")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError("archive member path must stay inside the bundle")
    return path.as_posix()


def _is_external_markdown_link(target: str) -> bool:
    lowered = target.strip().lower()
    return lowered.startswith(("http://", "https://", "mailto:", "tel:", "scholar-ai://", "#"))


def _resolve_markdown_link(member_name: str, target: str) -> str | None:
    """Resolve a bundle-relative Markdown link for soft broken-link warnings."""

    if not isinstance(target, str) or not target.strip():
        return None
    if _is_external_markdown_link(target):
        return None
    target = target.split("#", 1)[0].split("?", 1)[0].strip()
    if not target or not target.endswith(".md"):
        return None
    base = PurePosixPath(member_name).parent
    candidate = base.joinpath(target)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    return candidate.as_posix()


def validate_okf_markdown_document(
    relative_path: str | Path,
    text: str,
    *,
    known_paths: set[str] | None = None,
) -> dict[str, Any]:
    """Validate one OKF Markdown document with hard errors and soft warnings."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    member_name = _normalize_archive_member_name(Path(relative_path).as_posix())
    errors: list[str] = []
    warnings: list[str] = []
    if PurePosixPath(member_name).name in _OKF_RESERVED_MARKDOWN_NAMES:
        return {"path": member_name, "errors": errors, "warnings": warnings, "frontmatter": {}}

    frontmatter: dict[str, Any] = {}
    try:
        frontmatter, _body = parse_okf_frontmatter(text)
    except ValueError as exc:
        errors.append(str(exc))
        return {"path": member_name, "errors": errors, "warnings": warnings, "frontmatter": frontmatter}

    if not str(frontmatter.get("type") or "").strip():
        errors.append("OKF concept document requires non-empty frontmatter field: type")
    for optional_key in ("title", "description", "resource", "tags", "timestamp"):
        if optional_key not in frontmatter or frontmatter.get(optional_key) in (None, "", []):
            warnings.append(f"OKF optional frontmatter field is missing or empty: {optional_key}")
    if known_paths is not None:
        normalized_known_paths = {_normalize_archive_member_name(path) for path in known_paths}
        for match in _MARKDOWN_LINK_RE.finditer(text):
            resolved = _resolve_markdown_link(member_name, match.group(1))
            if resolved is not None and resolved not in normalized_known_paths:
                warnings.append(f"OKF link target is not present in bundle: {match.group(1)}")
    return {"path": member_name, "errors": errors, "warnings": warnings, "frontmatter": frontmatter}


def _render_okf_root_index(concepts: list[dict[str, Any]], *, generated_at_iso: str) -> str:
    """Render a root OKF index with progressive disclosure over exported pages."""

    frontmatter = {"okf_version": _OKF_VERSION}
    lines = [
        "# Scholar AI OKF Export",
        "",
        f"Generated at: `{generated_at_iso}`",
        "",
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for concept in concepts:
        grouped.setdefault(str(concept.get("type") or "Concept"), []).append(concept)
    for concept_type in sorted(grouped):
        lines.extend([f"# {concept_type}", ""])
        for concept in sorted(grouped[concept_type], key=lambda item: str(item.get("title") or "").lower()):
            description = str(concept.get("description") or "")
            suffix = f" - {description}" if description else ""
            lines.append(f"* [{concept.get('title')}]({concept.get('path')}){suffix}")
        lines.append("")
    return f"{_render_yaml_frontmatter(frontmatter)}\n{chr(10).join(lines).strip()}\n"


def _render_okf_log(*, generated_at_iso: str, page_count: int) -> str:
    """Render an OKF log entry for local export provenance."""

    date_part = generated_at_iso[:10]
    return (
        "# Scholar AI OKF Export Log\n\n"
        f"## {date_part}\n"
        f"* **Export**: Created a local Scholar AI OKF profile bundle with {page_count} wiki concept documents.\n"
    )


def _build_okf_bundle_manifest(
    concepts: list[dict[str, Any]],
    output_path: Path,
    *,
    generated_at_iso: str,
    warnings: list[str],
) -> dict[str, Any]:
    """Build the manifest for Scholar AI OKF-compatible bundles."""

    if not isinstance(output_path, Path):
        output_path = Path(output_path)
    resources = [
        {
            "role": "okf_concept",
            "path": concept["path"],
            "format": "markdown",
            "media_type": "text/markdown",
            "byte_count": concept.get("byte_count", 0),
        }
        for concept in concepts
    ]
    return {
        "schema_version": _OKF_BUNDLE_MANIFEST_SCHEMA_VERSION,
        "okf_version": _OKF_VERSION,
        "profile_schema_version": _OKF_PROFILE_SCHEMA_VERSION,
        "generated_at": generated_at_iso,
        "bundle": {
            "kind": "scholar_ai_okf_bundle",
            "entry_document": "index.md",
            "log_document": "log.md",
            "archive_filename": output_path.name,
            "manifest": _WIKI_EXPORT_MANIFEST_NAME,
        },
        "counts": {
            "concepts": len(concepts),
            "resources": len(resources),
            "warnings": len(warnings),
        },
        "concepts": concepts,
        "resources": resources,
        "warnings": list(warnings),
    }


def export_wiki_okf_bundle(
    page_store: WikiPageStore,
    output_path: Path,
    *,
    project_id: str | None = None,
    generated_at_iso: str | None = None,
) -> dict[str, Any]:
    """Export wiki pages as an OKF-compatible local Markdown bundle zip.

    The export is read-only with respect to source wiki pages and Zotero state.
    It writes a portable archive containing ``index.md``, ``log.md``, converted
    ``wiki/**/*.md`` concept documents, and ``manifest.json``.
    """

    _ensure_page_store_protocol(page_store)
    if not isinstance(output_path, Path):
        output_path = Path(output_path)
    if output_path.is_dir():
        raise ValueError("output_path must be a file path, not a directory")
    if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
        raise ValueError("project_id must be a non-empty string when provided")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = generated_at_iso or _utc_now_iso()
    errors: list[str] = []
    warnings: list[str] = []
    entries: list[tuple[str, str, dict[str, Any]]] = []

    for page_path in page_store.list_pages():
        try:
            content = page_store.read_page(page_path)
            if not content:
                continue
            source_frontmatter, body, page_warnings = _split_wiki_json_frontmatter(str(content))
            okf_path = f"wiki/{page_path.as_posix()}"
            page_prefix = f"{page_path.as_posix()}: "
            warnings.extend(f"{page_prefix}{warning}" for warning in page_warnings)
            okf_frontmatter = _build_okf_wiki_frontmatter(
                page_path,
                source_frontmatter,
                body,
                generated_at_iso=generated_at,
                project_id=project_id.strip() if project_id else None,
            )
            text = _render_okf_document(okf_frontmatter, body)
            entries.append((okf_path, text, okf_frontmatter))
        except Exception as exc:
            errors.append(f"Failed to convert {page_path}: {exc}")

    known_paths = {"index.md", "log.md", *[path for path, _text, _frontmatter in entries]}
    concepts: list[dict[str, Any]] = []
    for okf_path, text, okf_frontmatter in entries:
        validation = validate_okf_markdown_document(okf_path, text, known_paths=known_paths)
        errors.extend(f"{okf_path}: {error}" for error in validation["errors"])
        warnings.extend(f"{okf_path}: {warning}" for warning in validation["warnings"])
        concepts.append(
            {
                "path": okf_path,
                "type": okf_frontmatter.get("type"),
                "title": okf_frontmatter.get("title"),
                "description": okf_frontmatter.get("description"),
                "wiki_path": okf_frontmatter.get("wiki_path"),
                "byte_count": len(text.encode("utf-8")),
            }
        )

    manifest = _build_okf_bundle_manifest(
        concepts,
        output_path,
        generated_at_iso=generated_at,
        warnings=warnings,
    )

    try:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("index.md", _render_okf_root_index(concepts, generated_at_iso=generated_at))
            zf.writestr("log.md", _render_okf_log(generated_at_iso=generated_at, page_count=len(concepts)))
            for okf_path, text, _frontmatter in entries:
                zf.writestr(okf_path, text)
            zf.writestr(
                _WIKI_EXPORT_MANIFEST_NAME,
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
    except Exception as exc:
        return {
            "success": False,
            "page_count": 0,
            "output_path": str(output_path),
            "errors": [f"OKF export failed: {exc}"],
            "warnings": warnings,
            "manifest": manifest,
        }

    return {
        "success": len(errors) == 0,
        "page_count": len(concepts),
        "output_path": str(output_path),
        "errors": errors,
        "warnings": warnings,
        "manifest": manifest,
    }


def inspect_okf_bundle_archive(archive_path: Path) -> dict[str, Any]:
    """Validate an OKF zip archive without importing or mutating local state."""

    if not isinstance(archive_path, Path):
        archive_path = Path(archive_path)
    if not archive_path.is_file():
        raise FileNotFoundError(f"OKF archive not found: {archive_path}")

    errors: list[str] = []
    warnings: list[str] = []
    documents: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            raw_names = [name for name in zf.namelist() if not name.endswith("/")]
            safe_names: list[str] = []
            for raw_name in raw_names:
                try:
                    safe_names.append(_normalize_archive_member_name(raw_name))
                except ValueError as exc:
                    errors.append(f"{raw_name}: {exc}")
            known_paths = {name for name in safe_names if name.endswith(".md")}
            for member_name in safe_names:
                if not member_name.endswith(".md"):
                    continue
                text = zf.read(member_name).decode("utf-8")
                validation = validate_okf_markdown_document(member_name, text, known_paths=known_paths)
                errors.extend(f"{member_name}: {error}" for error in validation["errors"])
                warnings.extend(f"{member_name}: {warning}" for warning in validation["warnings"])
                if PurePosixPath(member_name).name not in _OKF_RESERVED_MARKDOWN_NAMES:
                    documents.append(
                        {
                            "path": member_name,
                            "type": validation["frontmatter"].get("type"),
                            "title": validation["frontmatter"].get("title") or PurePosixPath(member_name).stem,
                        }
                    )
    except zipfile.BadZipFile as exc:
        errors.append(f"OKF archive is not a valid zip file: {exc}")

    return {
        "schema_version": "scholar-ai-okf-inspection/v1",
        "archive_path": str(archive_path),
        "okf_version": _OKF_VERSION,
        "concept_count": len(documents),
        "documents": documents,
        "errors": errors,
        "warnings": warnings,
        "success": len(errors) == 0,
    }


def export_wiki_markdown(page_store: WikiPageStore, output_path: Path) -> dict[str, Any]:
    """Export all wiki pages as Markdown zip archive (G15 2026-05-26).

    Args:
        page_store: WikiPageStore instance
        output_path: Output zip file path

    Returns:
        Export result dict with success/page_count/output_path/errors

    Raises:
        ValueError: If output_path is a directory
    """
    if not isinstance(output_path, Path):
        output_path = Path(output_path)
    if output_path.is_dir():
        raise ValueError("output_path must be a file path, not a directory")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    errors = []
    page_count = 0
    exported_pages: list[dict[str, Any]] = []

    try:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for page_path in page_store.list_pages():
                try:
                    content = page_store.read_page(page_path)
                    if content:
                        page_archive_path = page_path.as_posix()
                        zf.writestr(page_archive_path, content)
                        exported_pages.append(
                            {
                                "path": page_archive_path,
                                "byte_count": len(content.encode("utf-8")),
                            }
                        )
                        page_count += 1
                except Exception as exc:
                    errors.append(f"Failed to export {page_path}: {exc}")
            manifest = _build_wiki_export_bundle_manifest(exported_pages, output_path)
            zf.writestr(
                _WIKI_EXPORT_MANIFEST_NAME,
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )

        return {
            "success": len(errors) == 0,
            "page_count": page_count,
            "output_path": str(output_path),
            "errors": errors,
        }
    except Exception as exc:
        return {
            "success": False,
            "page_count": 0,
            "output_path": str(output_path),
            "errors": [f"Export failed: {exc}"],
        }
